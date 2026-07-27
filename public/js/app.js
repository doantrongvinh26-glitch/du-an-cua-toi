(function () {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.panel');

  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabButtons.forEach((b) => b.classList.remove('active'));
      panels.forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });

  const FIELDS = {
    geminiApiKey: {
      input: document.getElementById('geminiApiKey'),
      status: document.getElementById('geminiApiKeyStatus'),
      toggle: document.getElementById('toggleGeminiApiKey'),
      save: document.getElementById('saveGeminiApiKey'),
      clear: document.getElementById('clearGeminiApiKey'),
    },
    labsToken: {
      input: document.getElementById('labsToken'),
      status: document.getElementById('labsTokenStatus'),
      toggle: document.getElementById('toggleLabsToken'),
      save: document.getElementById('saveLabsToken'),
      clear: document.getElementById('clearLabsToken'),
    },
  };

  function setStatus(field, text, kind) {
    const el = FIELDS[field].status;
    el.textContent = text;
    el.className = 'field-status' + (kind ? ' ' + kind : '');
  }

  function applySettings(data) {
    for (const field of Object.keys(FIELDS)) {
      const info = data[field] || {};
      if (info.hasValue) {
        FIELDS[field].input.value = '';
        FIELDS[field].input.placeholder = `Đã lưu (${info.masked})`;
        setStatus(field, `Đã lưu — ${info.masked}`, 'ok');
      } else {
        FIELDS[field].input.placeholder =
          field === 'geminiApiKey' ? 'Dán Gemini API Key vào đây' : 'Dán Labs Token vào đây';
        setStatus(field, 'Chưa lưu', '');
      }
    }
  }

  async function loadSettings() {
    const res = await fetch('/api/settings');
    const data = await res.json();
    applySettings(data);
  }

  async function saveField(field) {
    const value = FIELDS[field].input.value.trim();
    if (!value) {
      setStatus(field, 'Nhập giá trị trước khi lưu.', 'err');
      return;
    }
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value }),
    });
    const data = await res.json();
    applySettings(data);
  }

  async function clearField(field) {
    const res = await fetch(`/api/settings/${field}`, { method: 'DELETE' });
    const data = await res.json();
    applySettings(data);
  }

  for (const field of Object.keys(FIELDS)) {
    const { input, toggle, save, clear } = FIELDS[field];
    toggle.addEventListener('click', () => {
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      toggle.textContent = showing ? 'Hiện' : 'Ẩn';
    });
    save.addEventListener('click', () => saveField(field));
    clear.addEventListener('click', () => clearField(field));
  }

  loadSettings();
})();
