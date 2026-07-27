const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const express = require('express');
const settingsStore = require('./lib/settings-store');
const geminiClient = require('./lib/gemini-client');
const veoClient = require('./lib/veo-client');

const app = express();
const PORT = process.env.PORT || 3000;
const RENDERS_DIR = path.join(__dirname, '..', 'data', 'renders');

app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));
app.use('/renders', express.static(RENDERS_DIR));

app.get('/api/settings', (req, res) => {
  res.json(settingsStore.getMaskedSettings());
});

app.post('/api/settings', (req, res) => {
  const { geminiApiKey, labsToken } = req.body || {};
  const updated = settingsStore.saveSettings({ geminiApiKey, labsToken });
  res.json(updated);
});

app.delete('/api/settings/:field', (req, res) => {
  try {
    const updated = settingsStore.clearSetting(req.params.field);
    res.json(updated);
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

app.post('/api/prompts/generate', async (req, res) => {
  const { script } = req.body || {};
  if (!script || !script.trim()) {
    return res.status(400).json({ error: 'Thiếu kịch bản.' });
  }
  const apiKey = settingsStore.getSecret('geminiApiKey');
  if (!apiKey) {
    return res.status(400).json({ error: 'Chưa lưu Gemini API Key. Vào tab Cài đặt để thêm trước.' });
  }
  try {
    const scenes = await geminiClient.generateScenePrompts(script.trim(), apiKey);
    res.json({ scenes });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.post('/api/render/start', async (req, res) => {
  const { prompt } = req.body || {};
  if (!prompt || !prompt.trim()) {
    return res.status(400).json({ error: 'Thiếu prompt.' });
  }
  const apiKey = settingsStore.getSecret('geminiApiKey');
  if (!apiKey) {
    return res.status(400).json({ error: 'Chưa lưu Gemini API Key. Vào tab Cài đặt để thêm trước.' });
  }
  try {
    const operationName = await veoClient.startGeneration(prompt.trim(), apiKey);
    res.json({ operationName });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.get('/api/render/status', async (req, res) => {
  const { operation } = req.query;
  if (!operation) {
    return res.status(400).json({ error: 'Thiếu operation.' });
  }
  const apiKey = settingsStore.getSecret('geminiApiKey');
  if (!apiKey) {
    return res.status(400).json({ error: 'Chưa lưu Gemini API Key. Vào tab Cài đặt để thêm trước.' });
  }
  try {
    const result = await veoClient.pollOperation(operation, apiKey);
    if (!result.done) {
      return res.json({ done: false });
    }
    if (!fs.existsSync(RENDERS_DIR)) {
      fs.mkdirSync(RENDERS_DIR, { recursive: true });
    }
    const fileName = `${crypto.createHash('sha1').update(operation).digest('hex')}.mp4`;
    const destPath = path.join(RENDERS_DIR, fileName);
    if (!fs.existsSync(destPath)) {
      await veoClient.downloadVideo(result.uri, apiKey, destPath);
    }
    res.json({ done: true, videoUrl: `/renders/${fileName}` });
  } catch (err) {
    res.status(502).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Veo Scene Studio đang chạy tại http://localhost:${PORT}`);
});
