const fs = require('fs');

const API_BASE = 'https://generativelanguage.googleapis.com/v1beta';
const DEFAULT_MODEL = 'veo-3.1-fast-generate-preview';

async function startGeneration(prompt, apiKey, { model = DEFAULT_MODEL, aspectRatio, negativePrompt } = {}) {
  const url = `${API_BASE}/models/${model}:predictLongRunning`;
  const parameters = {};
  if (aspectRatio) parameters.aspectRatio = aspectRatio;
  if (negativePrompt) parameters.negativePrompt = negativePrompt;

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
    body: JSON.stringify({ instances: [{ prompt }], parameters }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Veo3 API lỗi khi bắt đầu render (${res.status}): ${text.slice(0, 300)}`);
  }

  const data = await res.json();
  if (!data.name) {
    throw new Error('Veo3 API không trả về operation name.');
  }
  return data.name;
}

async function pollOperation(operationName, apiKey) {
  const url = `${API_BASE}/${operationName}`;
  const res = await fetch(url, { headers: { 'x-goog-api-key': apiKey } });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Veo3 API lỗi khi kiểm tra tiến trình (${res.status}): ${text.slice(0, 300)}`);
  }

  const data = await res.json();
  if (data.error) {
    throw new Error(`Veo3 render lỗi: ${data.error.message || JSON.stringify(data.error)}`);
  }
  if (!data.done) {
    return { done: false };
  }

  const uri = data.response?.generateVideoResponse?.generatedSamples?.[0]?.video?.uri;
  if (!uri) {
    throw new Error('Render xong nhưng không tìm thấy video URI trong phản hồi.');
  }
  return { done: true, uri };
}

async function downloadVideo(uri, apiKey, destPath) {
  const res = await fetch(uri, { headers: { 'x-goog-api-key': apiKey } });
  if (!res.ok) {
    throw new Error(`Không tải được video render (${res.status}).`);
  }
  const buffer = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(destPath, buffer);
}

module.exports = { startGeneration, pollOperation, downloadVideo, DEFAULT_MODEL };
