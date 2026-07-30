/**
 * client.js — Client gọi TopView API để tạo ảnh và tạo video.
 *
 * Không phụ thuộc thư viện ngoài (dùng fetch có sẵn của Node 18+),
 * nên chép thẳng vào app nào cũng chạy: Node, Electron, Next.js...
 *
 * Cách dùng:
 *   const { TopViewClient } = require('./topview/client');
 *   const tv = new TopViewClient({ apiKey: process.env.TOPVIEW_API_KEY });
 *
 *   const anh = await tv.generateImage({ prompt: 'một ly cà phê trên bàn gỗ' });
 *   await tv.downloadTo(anh.url, 'anh.png');
 *
 *   const video = await tv.generateVideo({ prompt: 'quảng cáo cà phê 10 giây' });
 *   await tv.downloadTo(video.url, 'video.mp4');
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { pipeline } = require('stream/promises');
const { Readable } = require('stream');
const defaultConfig = require('./config');

/** Lỗi có ngữ cảnh, để app bắt và hiển thị cho người dùng. */
class TopViewError extends Error {
  constructor(message, { status, body, taskId } = {}) {
    super(message);
    this.name = 'TopViewError';
    this.status = status;
    this.body = body;
    this.taskId = taskId;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Lấy giá trị đầu tiên tìm được trong object theo danh sách tên khoá.
 * TopView trả về nhiều dạng khoá khác nhau tuỳ endpoint (taskId/task_id/id...),
 * nên tra theo nhiều tên để client không vỡ khi tên khoá đổi.
 */
function pick(obj, keys) {
  if (!obj || typeof obj !== 'object') return undefined;
  for (const k of keys) {
    if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
  }
  return undefined;
}

/** Tìm đệ quy URL file kết quả (http...) trong response có cấu trúc lồng nhau. */
function findUrl(node, depth = 0) {
  if (depth > 6 || node == null) return undefined;
  if (typeof node === 'string') {
    return /^https?:\/\//.test(node) ? node : undefined;
  }
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findUrl(item, depth + 1);
      if (found) return found;
    }
    return undefined;
  }
  if (typeof node === 'object') {
    // Ưu tiên các khoá hay dùng cho file kết quả.
    const preferred = pick(node, [
      'videoUrl', 'video_url', 'imageUrl', 'image_url',
      'url', 'downloadUrl', 'download_url', 'resultUrl', 'result_url', 'fileUrl',
    ]);
    if (typeof preferred === 'string' && /^https?:\/\//.test(preferred)) return preferred;
    for (const v of Object.values(node)) {
      const found = findUrl(v, depth + 1);
      if (found) return found;
    }
  }
  return undefined;
}

class TopViewClient {
  constructor(options = {}) {
    this.config = { ...defaultConfig, ...options };
    this.apiKey = options.apiKey || defaultConfig.apiKey;
    this.baseUrl = (options.baseUrl || defaultConfig.baseUrl).replace(/\/+$/, '');
    this.endpoints = { ...defaultConfig.endpoints, ...(options.endpoints || {}) };
    this.polling = { ...defaultConfig.polling, ...(options.polling || {}) };
    this.retryCfg = { ...defaultConfig.retry, ...(options.retry || {}) };
    // Hàm nhận thông báo tiến độ; mặc định không in gì (app tự gắn nếu muốn).
    this.onProgress = options.onProgress || (() => {});

    if (!this.apiKey) {
      throw new TopViewError(
        'Thiếu API key TopView. Đặt biến môi trường TOPVIEW_API_KEY ' +
        '(lấy tại https://www.topview.ai/api-settings).'
      );
    }
  }

  /** Gọi HTTP có retry cho lỗi mạng / lỗi 5xx / 429. */
  async request(pathname, { method = 'POST', body } = {}) {
    const url = pathname.startsWith('http') ? pathname : `${this.baseUrl}${pathname}`;
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      ...this.config.authHeaders(this.apiKey),
    };

    let lastErr;
    for (let attempt = 0; attempt < this.retryCfg.attempts; attempt++) {
      if (attempt > 0) {
        await sleep(this.retryCfg.backoffMs * 2 ** (attempt - 1));
      }
      let res;
      try {
        res = await fetch(url, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (err) {
        lastErr = new TopViewError(`Lỗi mạng khi gọi ${url}: ${err.message}`);
        continue; // thử lại
      }

      const text = await res.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        data = { raw: text };
      }

      if (res.ok) {
        // TopView bọc kết quả trong {code, message, result}. code != 200 là lỗi
        // nghiệp vụ (hết credit, tham số sai...) dù HTTP vẫn 200.
        const code = data && data.code !== undefined ? String(data.code) : '200';
        if (code !== '200' && code !== '0') {
          throw new TopViewError(
            `TopView báo lỗi (code ${code}): ${data.message || 'không rõ nguyên nhân'}`,
            { status: res.status, body: data }
          );
        }
        return data.result !== undefined ? data.result : data;
      }

      // 429/5xx thì thử lại, còn 4xx khác thì hỏng luôn.
      if (res.status === 429 || res.status >= 500) {
        lastErr = new TopViewError(
          `TopView trả về HTTP ${res.status}, sẽ thử lại...`,
          { status: res.status, body: data }
        );
        continue;
      }
      throw new TopViewError(
        `TopView trả về HTTP ${res.status}: ${data.message || text.slice(0, 300)}`,
        { status: res.status, body: data }
      );
    }
    throw lastErr;
  }

  /** Gửi tác vụ rồi chờ cho tới khi xong, trả về { url, taskId, raw }. */
  async submitAndWait(endpoint, payload, label = 'tác vụ') {
    const submitted = await this.request(endpoint, { method: 'POST', body: payload });
    const taskId = pick(submitted, ['taskId', 'task_id', 'id', 'jobId']);
    if (!taskId) {
      // Một số endpoint trả kết quả ngay, không cần chờ.
      const direct = findUrl(submitted);
      if (direct) return { url: direct, taskId: null, raw: submitted };
      throw new TopViewError(
        `Không tìm thấy taskId trong phản hồi khi tạo ${label}.`,
        { body: submitted }
      );
    }

    this.onProgress({ phase: 'submitted', taskId, label });
    return this.waitForTask(taskId, label);
  }

  /** Hỏi trạng thái tác vụ định kỳ cho tới khi thành công / thất bại / hết giờ. */
  async waitForTask(taskId, label = 'tác vụ') {
    const started = Date.now();
    const queryPath = this.endpoints.taskQuery.replace('{taskId}', encodeURIComponent(taskId));

    while (true) {
      if (Date.now() - started > this.polling.timeoutMs) {
        throw new TopViewError(
          `Quá thời gian chờ ${label} (${Math.round(this.polling.timeoutMs / 60000)} phút). ` +
          `Tác vụ có thể vẫn đang chạy, tra lại bằng taskId.`,
          { taskId }
        );
      }

      const result = await this.request(queryPath, { method: 'GET' });
      const status = String(
        pick(result, ['status', 'taskStatus', 'state']) || ''
      ).toLowerCase();

      if (['success', 'succeeded', 'completed', 'finished', 'done', '2'].includes(status)) {
        const url = findUrl(result);
        if (!url) {
          throw new TopViewError(
            `${label} báo thành công nhưng không có link file kết quả.`,
            { taskId, body: result }
          );
        }
        this.onProgress({ phase: 'done', taskId, label, url });
        return { url, taskId, raw: result };
      }

      if (['failed', 'failure', 'error', 'cancelled', 'canceled', '3'].includes(status)) {
        throw new TopViewError(
          `${label} thất bại: ${pick(result, ['message', 'errorMsg', 'error']) || 'không rõ nguyên nhân'}`,
          { taskId, body: result }
        );
      }

      const pct = pick(result, ['progress', 'percent']);
      this.onProgress({
        phase: 'running', taskId, label, status,
        progress: pct, elapsedMs: Date.now() - started,
      });
      await sleep(this.polling.intervalMs);
    }
  }

  /**
   * Tạo ảnh từ mô tả bằng chữ.
   * @param {object} opts - { prompt, aspectRatio, imageCount, ...tham số khác }
   */
  async generateImage({ prompt, aspectRatio = '1:1', imageCount = 1, ...rest } = {}) {
    if (!prompt) throw new TopViewError('Cần có "prompt" (mô tả ảnh muốn tạo).');
    return this.submitAndWait(
      this.endpoints.imageSubmit,
      { prompt, aspectRatio, imageCount, ...rest },
      'tạo ảnh'
    );
  }

  /**
   * Tạo video. Có thể từ mô tả chữ, hoặc từ ảnh có sẵn (truyền imageUrls).
   * @param {object} opts - { prompt, imageUrls, aspectRatio, duration, ... }
   */
  async generateVideo({ prompt, imageUrls, aspectRatio = '9:16', duration, ...rest } = {}) {
    if (!prompt && !(imageUrls && imageUrls.length)) {
      throw new TopViewError('Cần có "prompt" hoặc "imageUrls" để tạo video.');
    }
    const payload = { aspectRatio, ...rest };
    if (prompt) payload.prompt = prompt;
    if (imageUrls && imageUrls.length) payload.imageUrls = imageUrls;
    if (duration) payload.duration = duration;
    return this.submitAndWait(this.endpoints.videoSubmit, payload, 'tạo video');
  }

  /** Tải file kết quả về đĩa. Tự tạo thư mục cha nếu chưa có. */
  async downloadTo(url, destPath) {
    const dir = path.dirname(path.resolve(destPath));
    fs.mkdirSync(dir, { recursive: true });

    const res = await fetch(url);
    if (!res.ok) {
      throw new TopViewError(`Tải file thất bại (HTTP ${res.status}): ${url}`, { status: res.status });
    }
    await pipeline(Readable.fromWeb(res.body), fs.createWriteStream(destPath));
    this.onProgress({ phase: 'downloaded', path: destPath });
    return destPath;
  }
}

module.exports = { TopViewClient, TopViewError };
