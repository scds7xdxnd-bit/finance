(function(){
  const state = {
    initialized: false,
    onSuccess: null
  };

  function getModal(){
    return document.getElementById('quick-add-modal');
  }

  function getForm(){
    return document.getElementById('quick-add-form');
  }

  function getLinesContainer(){
    return document.getElementById('quick-add-lines');
  }

  function getBalanceNode(){
    return document.getElementById('quick-add-balance');
  }

  function getCsrfToken(){
    const windowToken = (window.FINANCE_CSRF_TOKEN || '').trim();
    if (windowToken) return windowToken;
    const meta = document.querySelector('meta[name="csrf-token"]');
    return ((meta && meta.getAttribute('content')) || '').trim();
  }

  function todayIso(){
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  function toAmount(value){
    const num = parseFloat(String(value || '').trim());
    return Number.isFinite(num) ? num : 0;
  }

  function createLineRow(initial){
    const line = initial || {};
    const row = document.createElement('div');
    row.className = 'qa-line-row';
    row.innerHTML = [
      '<select class="qa-line-dc">',
      '<option value="D">Debit</option>',
      '<option value="C">Credit</option>',
      '</select>',
      '<input type="text" class="qa-line-account" list="quick-add-account-options" placeholder="Account">',
      '<input type="number" class="qa-line-amount" step="0.01" min="0" placeholder="0.00">',
      '<input type="text" class="qa-line-memo" maxlength="255" placeholder="Memo (optional)">',
      '<button type="button" class="qa-line-remove" title="Remove line" aria-label="Remove line">&times;</button>'
    ].join('');
    const dc = row.querySelector('.qa-line-dc');
    const account = row.querySelector('.qa-line-account');
    const amount = row.querySelector('.qa-line-amount');
    const memo = row.querySelector('.qa-line-memo');
    dc.value = line.dc === 'C' ? 'C' : 'D';
    account.value = (line.account || line.account_name || '').trim();
    amount.value = line.amount && Number(line.amount) > 0 ? Number(line.amount).toFixed(2) : '';
    memo.value = (line.memo || '').trim();
    return row;
  }

  function setFormError(message){
    const form = getForm();
    if (!form) return;
    const node = form.querySelector('[data-role="form-error"]');
    if (!node) return;
    const text = (message || '').trim();
    if (!text){
      node.textContent = '';
      node.style.display = 'none';
      return;
    }
    node.textContent = text;
    node.style.display = 'block';
  }

  function getFieldErrorNode(fieldName){
    const form = getForm();
    if (!form) return null;
    const nodes = form.querySelectorAll('[data-field-error]');
    for (let i = 0; i < nodes.length; i += 1){
      if (nodes[i].getAttribute('data-field-error') === fieldName){
        return nodes[i];
      }
    }
    return null;
  }

  function setFieldError(fieldName, message){
    const node = getFieldErrorNode(fieldName);
    if (!node) return;
    node.textContent = (message || '').trim();
  }

  function clearErrors(){
    const form = getForm();
    if (!form) return;
    form.querySelectorAll('[data-field-error]').forEach((node) => {
      node.textContent = '';
    });
    setFormError('');
  }

  function refreshLineRemoveButtons(){
    const container = getLinesContainer();
    if (!container) return;
    const rows = Array.from(container.querySelectorAll('.qa-line-row'));
    const allowRemove = rows.length > 2;
    rows.forEach((row) => {
      const btn = row.querySelector('.qa-line-remove');
      if (!btn) return;
      btn.disabled = !allowRemove;
      btn.title = allowRemove ? 'Remove line' : 'At least two lines are required';
    });
  }

  function updateBalanceHint(){
    const container = getLinesContainer();
    const balance = getBalanceNode();
    if (!container || !balance) return;
    let debit = 0;
    let credit = 0;
    container.querySelectorAll('.qa-line-row').forEach((row) => {
      const dc = (row.querySelector('.qa-line-dc').value || 'D').toUpperCase();
      const amount = toAmount(row.querySelector('.qa-line-amount').value);
      if (amount <= 0) return;
      if (dc === 'C') credit += amount;
      else debit += amount;
    });
    const diff = debit - credit;
    const balanced = Math.abs(diff) < 0.005;
    const tone = balanced ? 'ok' : 'bad';
    balance.innerHTML = `Debits: ${debit.toFixed(2)} | Credits: ${credit.toFixed(2)} | <span class="${tone}">Diff: ${diff.toFixed(2)}</span>`;
  }

  function ensureMinimumRows(){
    const container = getLinesContainer();
    if (!container) return;
    while (container.querySelectorAll('.qa-line-row').length < 2){
      container.appendChild(createLineRow({ dc: container.children.length ? 'C' : 'D' }));
    }
    refreshLineRemoveButtons();
    updateBalanceHint();
  }

  function resetForm(prefill){
    const form = getForm();
    const container = getLinesContainer();
    if (!form || !container) return;
    clearErrors();
    const data = prefill || {};
    const dateInput = form.querySelector('[name="date"]');
    const descInput = form.querySelector('[name="description"]');
    if (dateInput){
      dateInput.value = (data.date || '').trim() || todayIso();
    }
    if (descInput){
      descInput.value = (data.description || '').trim().slice(0, 255);
    }
    container.innerHTML = '';
    const lines = Array.isArray(data.lines) && data.lines.length ? data.lines : [{ dc: 'D' }, { dc: 'C' }];
    lines.forEach((line) => container.appendChild(createLineRow(line)));
    ensureMinimumRows();
  }

  function normalizeFieldName(name){
    const key = String(name || '').toLowerCase();
    if (!key) return '';
    if (key === 'date' || key.includes('date')) return 'date';
    if (key === 'description' || key === 'desc' || key.includes('description')) return 'description';
    if (key === 'lines' || key.includes('line')) return 'lines';
    return '';
  }

  function coerceErrorText(value){
    if (Array.isArray(value)){
      return value.map(v => String(v || '').trim()).filter(Boolean).join(' ');
    }
    if (typeof value === 'string'){
      return value.trim();
    }
    if (value && typeof value === 'object' && typeof value.message === 'string'){
      return value.message.trim();
    }
    return '';
  }

  function extractFieldErrors(payload){
    if (!payload || typeof payload !== 'object') return {};
    const candidates = [payload.field_errors, payload.validation_errors, payload.errors];
    for (let i = 0; i < candidates.length; i += 1){
      const item = candidates[i];
      if (!item || Array.isArray(item) || typeof item !== 'object') continue;
      return item;
    }
    return {};
  }

  function applyServerErrors(payload){
    clearErrors();
    const fieldErrors = extractFieldErrors(payload);
    let mapped = false;
    Object.entries(fieldErrors).forEach(([key, value]) => {
      const fieldName = normalizeFieldName(key);
      const message = coerceErrorText(value);
      if (!fieldName || !message) return;
      setFieldError(fieldName, message);
      mapped = true;
    });
    const errorText = payload && typeof payload.error === 'string' ? payload.error.trim() : '';
    if (errorText){
      setFormError(errorText);
      return;
    }
    if (!mapped){
      setFormError('Unable to save entry.');
    }
  }

  function parseIsoDate(value){
    const raw = String(value || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
    const [yy, mm, dd] = raw.split('-').map(Number);
    const dt = new Date(Date.UTC(yy, mm - 1, dd));
    if (Number.isNaN(dt.getTime())) return null;
    if (dt.getUTCFullYear() !== yy || dt.getUTCMonth() + 1 !== mm || dt.getUTCDate() !== dd) return null;
    return raw;
  }

  function collectPayload(){
    const form = getForm();
    const container = getLinesContainer();
    if (!form || !container) return { valid: false, payload: null };
    clearErrors();
    let valid = true;

    const dateInput = form.querySelector('[name="date"]');
    const descInput = form.querySelector('[name="description"]');
    const parsedDate = parseIsoDate(dateInput ? dateInput.value : '');
    if (!parsedDate){
      setFieldError('date', 'Date is required and must be valid (YYYY-MM-DD).');
      valid = false;
    }

    const description = (descInput && descInput.value ? descInput.value : '').trim();
    if (!description){
      setFieldError('description', 'Description is required.');
      valid = false;
    } else if (description.length > 255){
      setFieldError('description', 'Description must be 255 characters or fewer.');
      valid = false;
    }

    const rows = Array.from(container.querySelectorAll('.qa-line-row'));
    if (rows.length < 2){
      setFieldError('lines', 'At least two lines are required.');
      valid = false;
    }

    const lines = [];
    let debit = 0;
    let credit = 0;
    const lineIssues = [];
    rows.forEach((row, idx) => {
      const dc = (row.querySelector('.qa-line-dc').value || '').trim().toUpperCase();
      const account = (row.querySelector('.qa-line-account').value || '').trim();
      const amount = toAmount(row.querySelector('.qa-line-amount').value);
      const memo = (row.querySelector('.qa-line-memo').value || '').trim();
      if (dc !== 'D' && dc !== 'C'){
        lineIssues.push(`Line ${idx + 1}: direction must be D or C.`);
      }
      if (!account){
        lineIssues.push(`Line ${idx + 1}: account is required.`);
      }
      if (!(amount > 0)){
        lineIssues.push(`Line ${idx + 1}: amount must be greater than zero.`);
      }
      if (dc === 'C') credit += amount;
      if (dc === 'D') debit += amount;
      lines.push({ dc, account, amount, memo });
    });
    if (lineIssues.length){
      setFieldError('lines', lineIssues[0]);
      valid = false;
    }
    if (Math.abs(debit - credit) > 0.005){
      setFieldError('lines', 'Debits and credits must balance.');
      valid = false;
    }
    updateBalanceHint();

    if (!valid){
      setFormError('Please fix the highlighted fields.');
      return { valid: false, payload: null };
    }
    return {
      valid: true,
      payload: {
        date: parsedDate,
        description,
        lines
      }
    };
  }

  function resolveAddEndpoint(){
    const registry = window.FINANCE_ENDPOINTS || {};
    const tx = registry.transactions || {};
    const url = String(tx.add || '').trim();
    if (url) return url;
    throw new Error('Configuration error: missing endpoint key transactions.add.');
  }

  function setBusy(isBusy){
    const form = getForm();
    if (!form) return;
    const submit = form.querySelector('[data-action="quick-add-submit"]');
    if (!submit) return;
    submit.disabled = !!isBusy;
    submit.textContent = isBusy ? 'Saving...' : 'Save Entry';
  }

  async function handleSubmit(event){
    event.preventDefault();
    const form = getForm();
    if (!form) return;
    const gathered = collectPayload();
    if (!gathered.valid || !gathered.payload) return;
    let url = '';
    try {
      url = resolveAddEndpoint();
    } catch (err){
      setFormError(err && err.message ? err.message : 'Quick Add configuration error.');
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken()
        },
        body: JSON.stringify(gathered.payload)
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false){
        applyServerErrors(payload);
        return;
      }
      closeModal();
      resetForm();
      if (typeof state.onSuccess === 'function'){
        await Promise.resolve(state.onSuccess(payload));
      }
    } catch (err){
      setFormError(err && err.message ? err.message : 'Unable to save entry.');
    } finally {
      setBusy(false);
    }
  }

  function openModal(prefill){
    if (!init()) return;
    const modal = getModal();
    resetForm(prefill);
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    const firstField = modal.querySelector('[name="date"]');
    if (firstField && typeof firstField.focus === 'function'){
      setTimeout(() => firstField.focus(), 0);
    }
  }

  function closeModal(){
    const modal = getModal();
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    setBusy(false);
    clearErrors();
  }

  function handleLineAction(action){
    const container = getLinesContainer();
    if (!container) return;
    if (action === 'quick-add-add-debit'){
      container.appendChild(createLineRow({ dc: 'D' }));
      refreshLineRemoveButtons();
      updateBalanceHint();
      return;
    }
    if (action === 'quick-add-add-credit'){
      container.appendChild(createLineRow({ dc: 'C' }));
      refreshLineRemoveButtons();
      updateBalanceHint();
    }
  }

  function init(){
    if (state.initialized) return true;
    const modal = getModal();
    const form = getForm();
    const lines = getLinesContainer();
    if (!modal || !form || !lines) return false;

    form.addEventListener('submit', handleSubmit);
    modal.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-action]');
      if (trigger){
        const action = trigger.getAttribute('data-action');
        if (action === 'quick-add-close'){
          event.preventDefault();
          closeModal();
          return;
        }
        if (action === 'quick-add-add-debit' || action === 'quick-add-add-credit'){
          event.preventDefault();
          handleLineAction(action);
          return;
        }
      }
      if (event.target.classList.contains('qa-line-remove')){
        event.preventDefault();
        const row = event.target.closest('.qa-line-row');
        if (row) row.remove();
        ensureMinimumRows();
      }
    });

    modal.addEventListener('keydown', (event) => {
      if (event.key === 'Escape'){
        closeModal();
      }
    });

    lines.addEventListener('input', () => {
      updateBalanceHint();
    });
    lines.addEventListener('change', () => {
      updateBalanceHint();
    });
    resetForm();
    state.initialized = true;
    return true;
  }

  const api = {
    open: openModal,
    close: closeModal,
    reset: resetForm,
    setOnSuccess(callback){
      state.onSuccess = typeof callback === 'function' ? callback : null;
    },
    isReady(){
      return init();
    }
  };

  window.QuickAddModal = api;

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
