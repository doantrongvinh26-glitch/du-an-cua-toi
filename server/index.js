const path = require('path');
const express = require('express');
const settingsStore = require('./lib/settings-store');
const geminiClient = require('./lib/gemini-client');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

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

app.listen(PORT, () => {
  console.log(`Veo Scene Studio đang chạy tại http://localhost:${PORT}`);
});
