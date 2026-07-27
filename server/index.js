const path = require('path');
const express = require('express');
const settingsStore = require('./lib/settings-store');

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

app.listen(PORT, () => {
  console.log(`Veo Scene Studio đang chạy tại http://localhost:${PORT}`);
});
