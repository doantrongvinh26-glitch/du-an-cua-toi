const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', '..', 'data');
const SETTINGS_FILE = path.join(DATA_DIR, 'settings.json');

const SECRET_FIELDS = ['geminiApiKey', 'labsToken'];

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
}

function readRaw() {
  if (!fs.existsSync(SETTINGS_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function mask(value) {
  if (!value) return null;
  if (value.length <= 4) return '••••';
  return `••••${value.slice(-4)}`;
}

// Trả về bản đã che giấu, không lộ giá trị thật ra frontend.
function getMaskedSettings() {
  const raw = readRaw();
  const result = {};
  for (const field of SECRET_FIELDS) {
    result[field] = {
      hasValue: Boolean(raw[field]),
      masked: mask(raw[field]),
    };
  }
  return result;
}

// Chỉ dùng ở server-side (khi gọi API Veo3/Labs thật), không expose qua route GET.
function getSecret(field) {
  const raw = readRaw();
  return raw[field] || null;
}

function saveSettings(partial) {
  ensureDataDir();
  const raw = readRaw();
  for (const field of SECRET_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(partial, field)) {
      const value = partial[field];
      if (typeof value === 'string' && value.trim()) {
        raw[field] = value.trim();
      }
    }
  }
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(raw, null, 2), { mode: 0o600 });
  return getMaskedSettings();
}

function clearSetting(field) {
  if (!SECRET_FIELDS.includes(field)) {
    throw new Error(`Trường không hợp lệ: ${field}`);
  }
  ensureDataDir();
  const raw = readRaw();
  delete raw[field];
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(raw, null, 2), { mode: 0o600 });
  return getMaskedSettings();
}

module.exports = { getMaskedSettings, getSecret, saveSettings, clearSetting, SECRET_FIELDS };
