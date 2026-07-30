#!/usr/bin/env node
/**
 * test-mock.js — Kiểm thử client TopView bằng server giả lập.
 *
 * Chạy: node topview/test-mock.js
 *
 * Không gọi API thật nên KHÔNG tốn credit và không cần API key.
 * Dùng để kiểm tra logic gửi tác vụ, chờ kết quả, tải file và xử lý lỗi
 * vẫn đúng sau khi bạn sửa client.
 */

'use strict';

const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');
const { TopViewClient, TopViewError } = require('./client');

const tasks = new Map();
let taskSeq = 0;

// --- Server giả lập TopView ---
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const send = (obj, status = 200) => {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(obj));
  };

  // File kết quả giả (ảnh/video).
  if (url.pathname === '/files/ket-qua.png') {
    res.writeHead(200, { 'Content-Type': 'image/png' });
    return res.end(Buffer.from('NOI-DUNG-ANH-GIA-LAP'));
  }

  // Gửi tác vụ: trả về taskId, cần hỏi thêm vài lần mới xong.
  if (url.pathname.endsWith('/task/submit')) {
    let body = '';
    req.on('data', (c) => (body += c));
    return req.on('end', () => {
      const payload = JSON.parse(body || '{}');
      // Trường hợp thử lỗi nghiệp vụ: code khác 200 dù HTTP 200.
      if (payload.prompt === 'HET_CREDIT') {
        return send({ code: '40001', message: 'Không đủ credit' });
      }
      const id = `task-${++taskSeq}`;
      tasks.set(id, {
        remaining: 2,                                   // hỏi 2 lần thì xong
        fail: payload.prompt === 'GAY_LOI',
      });
      send({ code: '200', message: 'Success', result: { taskId: id } });
    });
  }

  // Tra trạng thái tác vụ.
  if (url.pathname === '/v1/task/query') {
    const id = url.searchParams.get('taskId');
    const t = tasks.get(id);
    if (!t) return send({ code: '40400', message: 'Không tìm thấy tác vụ' });
    if (t.fail) {
      return send({ code: '200', result: { status: 'failed', message: 'Mô hình từ chối yêu cầu' } });
    }
    if (t.remaining-- > 0) {
      return send({ code: '200', result: { status: 'running', progress: 50 } });
    }
    return send({
      code: '200',
      result: { status: 'success', data: { videoUrl: `http://127.0.0.1:${port}/files/ket-qua.png` } },
    });
  }

  send({ code: '40400', message: 'Không có endpoint này' }, 404);
});

let port;
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'topview-test-'));

function makeClient(extra = {}) {
  return new TopViewClient({
    apiKey: 'khoa-gia-lap',
    baseUrl: `http://127.0.0.1:${port}`,
    polling: { intervalMs: 10, timeoutMs: 5000 },
    retry: { attempts: 2, backoffMs: 10 },
    ...extra,
  });
}

const ketQua = [];
function kiemTra(ten, dat) {
  ketQua.push({ ten, dat });
  console.log(`${dat ? '  OK  ' : ' HỎNG '} ${ten}`);
}

async function chay() {
  // 1. Tạo ảnh: gửi -> chờ -> nhận URL.
  const tv = makeClient();
  const anh = await tv.generateImage({ prompt: 'ly cà phê' });
  kiemTra('Tạo ảnh trả về URL kết quả', /^http:\/\/.+ket-qua\.png$/.test(anh.url));
  kiemTra('Tạo ảnh trả về taskId', typeof anh.taskId === 'string' && anh.taskId.length > 0);

  // 2. Chờ qua nhiều lần hỏi (mock bắt hỏi 3 lần mới xong).
  const moc = [];
  const tv2 = makeClient({ onProgress: (e) => moc.push(e.phase) });
  await tv2.generateVideo({ prompt: 'quảng cáo 10 giây' });
  kiemTra('Có báo tiến độ khi đang chạy', moc.includes('running'));
  kiemTra('Có báo hoàn tất', moc.includes('done'));

  // 3. Tải file về đĩa.
  const dich = path.join(tmpDir, 'sau/nhieu/cap/anh.png');
  await tv.downloadTo(anh.url, dich);
  kiemTra('Tải file và tự tạo thư mục cha', fs.existsSync(dich));
  kiemTra('Nội dung file tải về đúng',
    fs.readFileSync(dich, 'utf8') === 'NOI-DUNG-ANH-GIA-LAP');

  // 4. Lỗi nghiệp vụ (HTTP 200 nhưng code khác 200).
  let loi = null;
  try { await tv.generateImage({ prompt: 'HET_CREDIT' }); } catch (e) { loi = e; }
  kiemTra('Bắt được lỗi nghiệp vụ (hết credit)',
    loi instanceof TopViewError && /credit/i.test(loi.message));

  // 5. Tác vụ thất bại phía server.
  loi = null;
  try { await tv.generateVideo({ prompt: 'GAY_LOI' }); } catch (e) { loi = e; }
  kiemTra('Bắt được tác vụ thất bại',
    loi instanceof TopViewError && /thất bại/.test(loi.message));
  kiemTra('Lỗi có kèm taskId để tra cứu', !!(loi && loi.taskId));

  // 6. Thiếu API key phải báo rõ ràng.
  loi = null;
  try { new TopViewClient({ apiKey: '' }); } catch (e) { loi = e; }
  kiemTra('Báo lỗi rõ khi thiếu API key',
    loi instanceof TopViewError && /API key/i.test(loi.message));

  // 7. Thiếu tham số bắt buộc.
  loi = null;
  try { await tv.generateImage({}); } catch (e) { loi = e; }
  kiemTra('Báo lỗi khi thiếu prompt', loi instanceof TopViewError);

  // 8. Hết giờ chờ.
  const tvTimeout = makeClient({ polling: { intervalMs: 5, timeoutMs: 30 } });
  loi = null;
  try {
    // Tác vụ này cần nhiều lần hỏi hơn thời gian cho phép.
    tasks.set('task-cham', { remaining: 9999, fail: false });
    await tvTimeout.waitForTask('task-cham', 'tạo video');
  } catch (e) { loi = e; }
  kiemTra('Dừng đúng lúc khi quá thời gian chờ',
    loi instanceof TopViewError && /Quá thời gian/.test(loi.message));
}

server.listen(0, '127.0.0.1', async () => {
  port = server.address().port;
  try {
    await chay();
  } catch (err) {
    console.error('\nKiểm thử vỡ giữa chừng:', err);
    ketQua.push({ ten: 'chạy trọn bộ', dat: false });
  } finally {
    server.close();
    fs.rmSync(tmpDir, { recursive: true, force: true });
    const hong = ketQua.filter((r) => !r.dat);
    console.log(`\n${ketQua.length - hong.length}/${ketQua.length} mục đạt.`);
    process.exit(hong.length ? 1 : 0);
  }
});
