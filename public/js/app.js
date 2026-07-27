(function () {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.panel');

  function activateTab(name) {
    tabButtons.forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    panels.forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      activateTab(btn.dataset.tab);
      if (btn.dataset.tab === 'render') refreshRenderPreviews();
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

  const scriptInput = document.getElementById('scriptInput');
  const generateBtn = document.getElementById('generatePromptsBtn');
  const generateStatus = document.getElementById('generateStatus');
  const promptList = document.getElementById('promptList');

  let sceneTextareas = [];

  function renderScenes(scenes) {
    if (!scenes.length) {
      promptList.innerHTML = '<p class="coming-soon">Không sinh được cảnh nào, thử lại với kịch bản chi tiết hơn.</p>';
      return;
    }
    promptList.innerHTML = '';
    sceneTextareas = [];
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
      const textarea = card.querySelector('textarea');
      sceneTextareas.push(textarea);
      card.querySelector('.copy-btn').addEventListener('click', (e) => {
        navigator.clipboard.writeText(textarea.value).then(() => {
          e.target.textContent = 'Đã chép!';
          setTimeout(() => { e.target.textContent = 'Sao chép'; }, 1500);
        });
      });
      promptList.appendChild(card);
    });
    buildRenderTab(scenes);
  }

  const renderList = document.getElementById('renderList');
  const renderAllBtn = document.getElementById('renderAllBtn');
  const renderAllStatus = document.getElementById('renderAllStatus');
  let renderCards = [];

  function buildRenderTab(scenes) {
    renderList.innerHTML = '';
    renderCards = [];
    scenes.forEach((scene, i) => {
      const card = document.createElement('div');
      card.className = 'scene-card';
      card.innerHTML = `
        <h3>Cảnh ${scene.index ?? i + 1}</h3>
        <div class="scene-prompt-preview"></div>
        <div class="scene-actions">
          <button class="btn-primary render-btn" type="button">Render</button>
          <span class="scene-render-status">Chưa render</span>
        </div>
      `;
      card.querySelector('.scene-prompt-preview').textContent = sceneTextareas[i] ? sceneTextareas[i].value : (scene.veo3Prompt || '');
      const entry = { card, renderBtn: card.querySelector('.render-btn'), statusEl: card.querySelector('.scene-render-status') };
      entry.renderBtn.addEventListener('click', () => runRender(i, entry));
      renderList.appendChild(card);
      renderCards.push(entry);
    });
  }

  function refreshRenderPreviews() {
    renderCards.forEach((entry, i) => {
      const previewEl = entry.card.querySelector('.scene-prompt-preview');
      if (previewEl && sceneTextareas[i]) previewEl.textContent = sceneTextareas[i].value;
    });
  }

  async function runRender(index, entry) {
    const prompt = sceneTextareas[index] ? sceneTextareas[index].value.trim() : '';
    if (!prompt) {
      entry.statusEl.textContent = 'Thiếu prompt.';
      entry.statusEl.className = 'scene-render-status err';
      return;
    }
    entry.renderBtn.disabled = true;
    entry.statusEl.textContent = 'Đang gửi yêu cầu tới Veo3...';
    entry.statusEl.className = 'scene-render-status';
    try {
      const startRes = await fetch('/api/render/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      });
      const startData = await startRes.json();
      if (!startRes.ok) {
        entry.statusEl.textContent = startData.error || 'Có lỗi khi bắt đầu render.';
        entry.statusEl.className = 'scene-render-status err';
        return;
      }
      const operation = startData.operationName;
      const startTime = Date.now();
      for (;;) {
        await new Promise((r) => setTimeout(r, 8000));
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        entry.statusEl.textContent = `Đang render... (${elapsed}s)`;
        const statusRes = await fetch(`/api/render/status?operation=${encodeURIComponent(operation)}`);
        const statusData = await statusRes.json();
        if (!statusRes.ok) {
          entry.statusEl.textContent = statusData.error || 'Có lỗi khi kiểm tra tiến trình.';
          entry.statusEl.className = 'scene-render-status err';
          return;
        }
        if (statusData.done) {
          entry.statusEl.textContent = `Render xong (${elapsed}s).`;
          entry.statusEl.className = 'scene-render-status ok';
          let video = entry.card.querySelector('video');
          if (!video) {
            video = document.createElement('video');
            video.controls = true;
            entry.card.appendChild(video);
          }
          video.src = statusData.videoUrl;
          let downloadLink = entry.card.querySelector('.download-link');
          if (!downloadLink) {
            downloadLink = document.createElement('a');
            downloadLink.className = 'link-btn download-link';
            downloadLink.textContent = 'Tải video về';
            downloadLink.target = '_blank';
            entry.card.appendChild(downloadLink);
          }
          downloadLink.href = statusData.videoUrl;
          return;
        }
      }
    } catch (err) {
      entry.statusEl.textContent = 'Không kết nối được tới server.';
      entry.statusEl.className = 'scene-render-status err';
    } finally {
      entry.renderBtn.disabled = false;
    }
  }

  renderAllBtn.addEventListener('click', async () => {
    if (!renderCards.length) {
      renderAllStatus.textContent = 'Chưa có cảnh nào để render.';
      renderAllStatus.className = 'field-status err';
      return;
    }
    renderAllBtn.disabled = true;
    for (let i = 0; i < renderCards.length; i++) {
      renderAllStatus.textContent = `Đang render cảnh ${i + 1}/${renderCards.length}...`;
      renderAllStatus.className = 'field-status';
      await runRender(i, renderCards[i]);
    }
    renderAllStatus.textContent = 'Đã render xong tất cả các cảnh.';
    renderAllStatus.className = 'field-status ok';
    renderAllBtn.disabled = false;
  });

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
