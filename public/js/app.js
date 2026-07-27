(function () {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.panel');

  function activateTab(name) {
    tabButtons.forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    panels.forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => activateTab(btn.dataset.tab));
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

  const scriptInput = document.getElementById('scriptInput');
  const generateBtn = document.getElementById('generatePromptsBtn');
  const generateStatus = document.getElementById('generateStatus');
  const promptList = document.getElementById('promptList');

  function renderScenes(scenes) {
    if (!scenes.length) {
      promptList.innerHTML = '<p class="coming-soon">Không sinh được cảnh nào, thử lại với kịch bản chi tiết hơn.</p>';
      return;
    }
    promptList.innerHTML = '';
    scenes.forEach((scene, i) => {
      const card = document.createElement('div');
      card.className = 'scene-card';
      card.innerHTML = `
        <h3>Cảnh ${scene.index ?? i + 1}</h3>
        <p class="scene-summary">${(scene.summary || '').replace(/</g, '&lt;')}</p>
        <textarea rows="4">${(scene.veo3Prompt || '').replace(/</g, '&lt;')}</textarea>
        <div class="scene-actions">
          <button class="btn-secondary copy-btn" type="button">Sao chép</button>
        </div>
      `;
      card.querySelector('.copy-btn').addEventListener('click', (e) => {
        const text = card.querySelector('textarea').value;
        navigator.clipboard.writeText(text).then(() => {
          e.target.textContent = 'Đã chép!';
          setTimeout(() => { e.target.textContent = 'Sao chép'; }, 1500);
        });
      });
      promptList.appendChild(card);
    });
  }

  generateBtn.addEventListener('click', async () => {
    const script = scriptInput.value.trim();
    if (!script) {
      generateStatus.textContent = 'Nhập kịch bản trước khi sinh prompt.';
      generateStatus.className = 'field-status err';
      return;
    }
    generateBtn.disabled = true;
    generateStatus.textContent = 'Đang sinh prompt...';
    generateStatus.className = 'field-status';
    try {
      const res = await fetch('/api/prompts/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script }),
      });
      const data = await res.json();
      if (!res.ok) {
        generateStatus.textContent = data.error || 'Có lỗi xảy ra.';
        generateStatus.className = 'field-status err';
        return;
      }
      generateStatus.textContent = `Đã sinh ${data.scenes.length} cảnh.`;
      generateStatus.className = 'field-status ok';
      renderScenes(data.scenes);
      activateTab('prompt');
    } catch (err) {
      generateStatus.textContent = 'Không kết nối được tới server.';
      generateStatus.className = 'field-status err';
    } finally {
      generateBtn.disabled = false;
    }
  });
})();
