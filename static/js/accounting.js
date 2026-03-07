// Accounting page JS extracted
(function(){
  const BOOT = window.ACC_BOOT || {categoryMap:{}, csrfToken:''};
  const categoryMap = BOOT.categoryMap;
  const csrfToken = BOOT.csrfToken;
  const folderColorMap = {};

  async function postJSON(url, payload) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify(payload) });
    if (!res.ok) throw new Error('Request failed');
    return res.json().catch(() => ({}));
  }

  function showView(view) {
    const foldersBtn = document.getElementById('btn-view-folders');
    const accountsBtn = document.getElementById('btn-view-accounts');
    const journalBtn = document.getElementById('btn-view-journal');
    const trialBtn = document.getElementById('btn-view-trial');
    const receivablesBtn = document.getElementById('btn-view-receivables');
    const foldersView = document.getElementById('folders-view');
    const accountsView = document.getElementById('accounts-view');
    const journalView = document.getElementById('journal-view');
    const trialView = document.getElementById('trial-view');
    const receivablesView = document.getElementById('receivables-view');
    const isFolders = view === 'folders';
    const isAccounts = view === 'accounts';
    const isJournal = view === 'journal';
    const isTrial = view === 'trial';
    const isReceivables = view === 'receivables';
    if (foldersBtn) foldersBtn.classList.toggle('active', isFolders);
    if (accountsBtn) accountsBtn.classList.toggle('active', isAccounts);
    if (journalBtn) journalBtn.classList.toggle('active', isJournal);
    if (trialBtn) trialBtn.classList.toggle('active', isTrial);
    if (receivablesBtn) receivablesBtn.classList.toggle('active', isReceivables);
    if (foldersView) foldersView.style.display = isFolders ? 'grid' : 'none';
    if (accountsView) accountsView.style.display = isAccounts ? 'block' : 'none';
    if (journalView) journalView.style.display = isJournal ? 'block' : 'none';
    if (trialView) trialView.style.display = isTrial ? 'block' : 'none';
    if (receivablesView) receivablesView.style.display = isReceivables ? 'block' : 'none';
    try { localStorage.setItem('accountingView', view); } catch(_){}
    if (isJournal && typeof window.ensureJournalLoaded === 'function') {
      window.ensureJournalLoaded();
    }
    if (isReceivables && typeof window.initReceivableDebtUI === 'function') {
      window.initReceivableDebtUI();
    }
  }

  async function addCategory(where='sidebar') {
    const input = document.querySelector(where === 'sidebar' ? '#add-cat' : '#modal-add-cat');
    const name = (input && input.value || '').trim();
    if (!name) return;
    const data = await postJSON('/accounting/category/add', { name });
    if (data && data.ok) { window.location.reload(); }
  }

  let selectedFolderId = null;
  function selectFolder(id) {
    selectedFolderId = id;
    try { localStorage.setItem('lastFolderId', String(id)); } catch(_){}
    document.querySelectorAll('.folder-item').forEach(el => el.classList.toggle('active', parseInt(el.dataset.id,10)===id));
    document.querySelectorAll('.in-folder-panel').forEach(p => p.style.display = (parseInt(p.dataset.folderId,10)===id) ? 'block' : 'none');
    const h = document.getElementById('in-folder-title');
    if (h) { h.textContent = 'In Folder: ' + (categoryMap[id] || ''); }
    filterNotInFolderList();
    const paneMid = document.getElementById('pane-in-folder');
    const paneRight = document.getElementById('pane-notin');
    if (paneMid) paneMid.style.display = 'block';
    if (paneRight) paneRight.style.display = 'block';
  }

  function filterNotInFolderList() {
    const q = (document.getElementById('notin-search')?.value || '').toLowerCase();
    const list = document.getElementById('notin-list');
    if (!list) return;
    list.querySelectorAll('.account-row').forEach(it => {
      const name = (it.dataset.name || '').toLowerCase();
      const cat = it.dataset.catId ? parseInt(it.dataset.catId,10) : null;
      const hide = (selectedFolderId!=null && cat===selectedFolderId) || (q && !name.includes(q));
      it.style.display = hide ? 'none' : '';
      const badge = it.querySelector('.folder-badge');
      if (badge) {
        if (cat) { badge.textContent = categoryMap[cat] || 'Folder'; badge.style.background = folderColorMap[cat] || '#4dabf7'; }
        else { badge.textContent = 'Unassigned'; badge.style.background = '#adb5bd'; }
      }
    });
  }

  function applyBadgeColorFor(el, catId) {
    const badge = el.querySelector('.folder-badge');
    if (!badge) return;
    if (catId) { badge.textContent = categoryMap[catId] || 'Folder'; badge.style.background = folderColorMap[catId] || '#4dabf7'; }
    else { badge.textContent = 'Unassigned'; badge.style.background = '#adb5bd'; }
  }

  function naturalKey(row) {
    const code = (row.dataset.code || '').trim();
    if (code && /^\d+$/.test(code)) return ['0', parseInt(code, 10), ''];
    const name = (row.dataset.name || '').trim().toLowerCase();
    const parts = name.match(/\d+|\D+/g) || [];
    return parts.map(p => (/^\d+$/.test(p) ? parseInt(p,10) : p));
  }
  function resortNodeList(container) {
    const rows = Array.from(container.querySelectorAll('.account-row'));
    rows.sort((a,b) => {
      const ka = naturalKey(a), kb = naturalKey(b);
      const len = Math.max(ka.length, kb.length);
      for (let i=0;i<len;i++) {
        const va = ka[i], vb = kb[i];
        if (va === undefined) return -1;
        if (vb === undefined) return 1;
        if (typeof va === 'number' && typeof vb === 'number') {
          if (va !== vb) return va - vb;
        } else {
          const sa = String(va), sb = String(vb);
          if (sa !== sb) return sa < sb ? -1 : 1;
        }
      }
      return 0;
    });
    rows.forEach(r => container.appendChild(r));
  }

  function createAccountRow(id, name, code, currency) {
    const row = document.createElement('div');
    row.className = 'account-row';
    row.setAttribute('draggable', 'true');
    row.dataset.id = String(id);
    row.dataset.name = name;
    if (code) row.dataset.code = code; else row.dataset.code = '';
    row.dataset.currency = (currency || 'KRW').toUpperCase();
    const main = document.createElement('div');
    main.className = 'row-main';
    const currencySpan = document.createElement('span');
    currencySpan.className = 'badge currency-badge';
    currencySpan.dataset.ccy = row.dataset.currency;
    currencySpan.textContent = row.dataset.currency;
    main.appendChild(currencySpan);
    main.appendChild(document.createTextNode(' '));
    const strong = document.createElement('strong');
    strong.textContent = name;
    main.appendChild(strong);
    const actions = document.createElement('div');
    actions.className = 'row-actions';
    const btnMove = document.createElement('button');
    btnMove.className = 'icon-btn'; btnMove.title = 'Move'; btnMove.innerHTML = '<i class="fa fa-right-left"></i>';
    btnMove.addEventListener('click', () => openMoveModalFromButton(btnMove));
    const kebab = document.createElement('div');
    kebab.className = 'kebab';
    const kebabBtn = document.createElement('button');
    kebabBtn.className = 'kebab-btn'; kebabBtn.title = 'More'; kebabBtn.innerHTML = '<i class="fa fa-ellipsis-vertical"></i>';
    kebabBtn.addEventListener('click', (e) => { e.stopPropagation(); toggleRowMenu(kebabBtn); });
    const dd = document.createElement('div');
    dd.className = 'dropdown';
    const miRename = document.createElement('button');
    miRename.className = 'menu-item'; miRename.innerHTML = '<i class="fa fa-pen"></i> Rename';
    miRename.addEventListener('click', () => renameAccountFromButton(miRename));
    const miUnassign = document.createElement('button');
    miUnassign.className = 'menu-item'; miUnassign.style.color = '#b22222'; miUnassign.innerHTML = '<i class="fa fa-unlink"></i> Unassign';
    miUnassign.addEventListener('click', () => unassignAccount(id));
    dd.append(miRename, miUnassign);
    kebab.append(kebabBtn, dd);
    actions.append(btnMove, kebab);
    row.append(main, actions);
    row.addEventListener('dragstart', onDragStart);
    row.addEventListener('dragend', onDragEnd);
    return row;
  }

  function afterMoveUpdate(accId, newCatId) {
    const rightItem = document.querySelector(`#notin-list .account-row[data-id='${accId}']`);
    if (rightItem) {
      rightItem.dataset.catId = newCatId ? String(newCatId) : '';
      applyBadgeColorFor(rightItem, newCatId);
      filterNotInFolderList();
    }
    const accItem = document.querySelector(`#acc-list .account-row[data-id='${accId}']`);
    if (accItem) {
      accItem.dataset.catId = newCatId ? String(newCatId) : '';
      applyBadgeColorFor(accItem, newCatId);
    }
    if (selectedFolderId && (!newCatId || parseInt(newCatId,10) !== selectedFolderId)) {
      const row = document.querySelector(`.in-folder-panel[data-folder-id='${selectedFolderId}'] .account-row[data-id='${accId}']`);
      if (row && row.parentElement) row.parentElement.removeChild(row);
    }
    if (selectedFolderId && newCatId && parseInt(newCatId,10) === selectedFolderId) {
      const panel = document.querySelector(`.in-folder-panel[data-folder-id='${selectedFolderId}']`);
      if (panel) {
        if (!panel.querySelector(`.account-row[data-id='${accId}']`)) {
          const src = rightItem || accItem;
          const name = src ? (src.dataset.name || src.querySelector('strong')?.textContent || '') : '';
          const code = src ? (src.dataset.code || '') : '';
          const currency = src ? (src.dataset.currency || 'KRW') : 'KRW';
          const newRow = createAccountRow(accId, name, code, currency);
          newRow.dataset.catId = String(selectedFolderId || '');
          panel.appendChild(newRow);
        }
        resortNodeList(panel);
      }
    }
    const notin = document.getElementById('notin-list'); if (notin) resortNodeList(notin);
    const accl = document.getElementById('acc-list'); if (accl) resortNodeList(accl);
  }

  async function moveToSelectedFolder(accId) {
    if (selectedFolderId == null) return;
    await postJSON('/accounting/account/move', { account_id: accId, category_id: selectedFolderId, order: 9999 });
    afterMoveUpdate(accId, selectedFolderId);
  }

  function unassignAccount(accId) {
    postJSON('/accounting/account/move', { account_id: accId, category_id: null, order: 9999 })
      .then(() => afterMoveUpdate(accId, null))
      .catch(err => console.error(err));
  }

  function updateAllBadges() {
    document.querySelectorAll('.account-row .folder-badge').forEach(badge => {
      const row = badge.closest('.account-row');
      const catIdStr = row ? row.dataset.catId : '';
      const catId = catIdStr ? parseInt(catIdStr,10) : null;
      if (catId) { badge.textContent = categoryMap[catId] || 'Folder'; badge.style.background = folderColorMap[catId] || '#4dabf7'; }
      else { badge.textContent = 'Unassigned'; badge.style.background = '#adb5bd'; }
    });
  }

  async function deleteAccountFromButton(btn){
    try{
      const row = btn.closest('.account-row'); if (!row) return;
      const id = parseInt(row.dataset.id || '0', 10); if (!id) return;
      if (!confirm('Delete this account?')) return;
      const res = await fetch(`/accounting/account/delete/${id}`, { method: 'POST', headers: { 'Content-Type':'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify({}) });
      if (!res.ok) return;
      // Remove from Accounts view list
      document.querySelectorAll(`.account-row[data-id='${id}']`).forEach(el => el.remove());
      // Remove from Find Accounts and In Folder panels if present
      const notin = document.querySelector(`#notin-list .account-row[data-id='${id}']`); if (notin) notin.remove();
      document.querySelectorAll(`.in-folder-panel .account-row[data-id='${id}']`).forEach(el => el.remove());
    }catch(e){ console.error(e); }
  }

  function deselectFolder() {
    selectedFolderId = null;
    try { localStorage.removeItem('lastFolderId'); } catch(_){}
    document.querySelectorAll('.folder-item').forEach(el => el.classList.remove('active'));
    const paneMid = document.getElementById('pane-in-folder');
    const paneRight = document.getElementById('pane-notin');
    if (paneMid) paneMid.style.display = 'none';
    if (paneRight) paneRight.style.display = 'none';
    const s = document.getElementById('notin-search'); if (s) s.value = '';
    filterNotInFolderList();
  }

  let dragItem = null;
  function onDragStart(e) {
    const el = e.currentTarget;
    dragItem = { type: 'account', id: parseInt(el.dataset.id, 10) };
    el.classList.add('ghost');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', JSON.stringify(dragItem));
  }
  function onDragEnd(e) { e.currentTarget.classList.remove('ghost'); }
  function onDragOverList(e) { e.preventDefault(); e.currentTarget.classList.add('drop-target'); }
  function onDragLeaveList(e) { e.currentTarget.classList.remove('drop-target'); }
  async function onDropToList(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drop-target');
    let data; try { data = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (_) { return; }
    if (!data || data.type !== 'account') return;
    const catId = parseInt(e.currentTarget.dataset.categoryId, 10);
    const order = e.currentTarget.querySelectorAll('.account-row').length;
    try { await postJSON('/accounting/account/move', { account_id: data.id, category_id: catId, order }); afterMoveUpdate(data.id, catId); } catch (e) { console.error(e); }
  }

  function filterAccountsView() {
    const q = (document.getElementById('acc-search')?.value || '').toLowerCase();
    const onlyUncat = document.getElementById('acc-only-uncat')?.checked;
    const folderFilter = document.getElementById('acc-folder-filter')?.value;
    const list = document.getElementById('acc-list'); if (!list) return;
    list.querySelectorAll('.account-row').forEach(it => {
      const name = (it.dataset.name || '').toLowerCase();
      const cat = it.dataset.catId || '';
      let show = (!q || name.includes(q));
      if (folderFilter) show = show && (cat === folderFilter);
      else if (onlyUncat) show = show && (!cat);
      it.style.display = show ? '' : 'none';
    });
  }

  // Selection state for Accounts tab
  const selectedAccIds = new Set();
  function updateSelectedCount(){ const el = document.getElementById('acc-selected-count'); if (el) el.textContent = `${selectedAccIds.size} selected`; const all = document.getElementById('acc-select-all'); if (all){ const boxes = document.querySelectorAll('#acc-list .acc-select'); const total = Array.from(boxes).filter(b => b.closest('.account-row')?.style.display !== 'none').length; all.checked = (selectedAccIds.size>0 && selectedAccIds.size===total); all.indeterminate = (selectedAccIds.size>0 && selectedAccIds.size<total); } }
  function bindSelectionHandlers(){
    document.querySelectorAll('#acc-list .acc-select').forEach(cb => {
      cb.addEventListener('change', () => {
        const id = parseInt(cb.dataset.id||'0',10); if (!id) return;
        if (cb.checked) selectedAccIds.add(id); else selectedAccIds.delete(id);
        updateSelectedCount();
      });
    });
    const all = document.getElementById('acc-select-all'); if (all){
      all.addEventListener('change', () => {
        const boxes = document.querySelectorAll('#acc-list .acc-select');
        boxes.forEach(cb => {
          const row = cb.closest('.account-row'); if (row && row.style.display==='none') return;
          cb.checked = all.checked; const id = parseInt(cb.dataset.id||'0',10); if (!id) return; if (all.checked) selectedAccIds.add(id); else selectedAccIds.delete(id);
        });
        updateSelectedCount();
      });
    }
    const bulkMove = document.getElementById('acc-bulk-move'); if (bulkMove){ bulkMove.addEventListener('click', () => { if (selectedAccIds.size===0) return; openBulkMoveModal(); }); }
    const bulkUn = document.getElementById('acc-bulk-unassign'); if (bulkUn){ bulkUn.addEventListener('click', () => { if (selectedAccIds.size===0) return; bulkUnassign(Array.from(selectedAccIds)); }); }
    const bulkCcyBtn = document.getElementById('acc-bulk-ccy-apply');
    if (bulkCcyBtn){
      bulkCcyBtn.addEventListener('click', async () => {
        if (selectedAccIds.size === 0) return;
        const sel = document.getElementById('acc-bulk-ccy-select');
        const ccy = sel ? (sel.value || 'KRW') : 'KRW';
        try {
          const res = await fetch('/accounting/account/bulk_currency', {
            method:'POST',
            headers:{ 'Content-Type':'application/json','X-CSRF-Token': csrfToken },
            credentials:'same-origin',
            body: JSON.stringify({ account_ids: Array.from(selectedAccIds), currency_code: ccy })
          });
          const data = await res.json().catch(()=>({}));
          if (!res.ok || !data.ok) throw new Error(data.error || 'Failed to assign currency');
          window.location.reload();
        } catch (e){ console.error(e); alert(e.message || 'Failed to assign currency.'); }
      });
    }
  }
  async function bulkUnassign(ids){
    try{
      const res = await fetch('/accounting/account/bulk_unassign', { method:'POST', headers:{ 'Content-Type':'application/json','X-CSRF-Token': csrfToken }, body: JSON.stringify({ account_ids: ids }) });
      if (res.ok){ ids.forEach(id => { afterMoveUpdate(id, null); const cb = document.querySelector(`#acc-list .acc-select[data-id='${id}']`); if (cb){ cb.checked=false; selectedAccIds.delete(id); } }); updateSelectedCount(); }
    }catch(e){ console.error(e); }
  }
  // Bulk move uses existing modal with a custom label and handler
  let bulkMoveIds = null;
  function openBulkMoveModal(){
    bulkMoveIds = Array.from(selectedAccIds);
    window.bulkMoveIds = bulkMoveIds;
    const title = document.getElementById('modal-acc-name'); if (title) title.textContent = `${bulkMoveIds.length} selected`;
    const modal = document.getElementById('modal'); if (modal) modal.style.display = 'flex';
  }
  async function modalMoveToBulk(catId){
    if (!bulkMoveIds || bulkMoveIds.length===0) return;
    try{
      const res = await fetch('/accounting/account/bulk_move', { method:'POST', headers:{ 'Content-Type':'application/json','X-CSRF-Token': csrfToken }, body: JSON.stringify({ account_ids: bulkMoveIds, category_id: catId }) });
      if (res.ok){ bulkMoveIds.forEach(id => afterMoveUpdate(id, catId)); selectedAccIds.clear(); updateSelectedCount(); }
    }catch(e){ console.error(e); }
    bulkMoveIds = null; window.bulkMoveIds = null; closeMoveModal();
  }

  let modalAccId = null;
  function openMoveModal(accId, accName) {
    modalAccId = accId;
    const title = document.getElementById('modal-acc-name'); if (title) title.textContent = accName;
    const modal = document.getElementById('modal'); if (modal) modal.style.display = 'flex';
  }
  function closeMoveModal() { const modal = document.getElementById('modal'); if (modal) modal.style.display = 'none'; modalAccId = null; }
  async function modalAddFolder() { await addCategory('modal'); }
  async function modalMoveTo(catId) {
    if (!modalAccId) return;
    await postJSON('/accounting/account/move', { account_id: modalAccId, category_id: catId, order: 9999 });
    afterMoveUpdate(modalAccId, catId); closeMoveModal();
  }
  function openMoveModalFromButton(btn) {
    const row = btn.closest('.account-row');
    const id = parseInt(row?.dataset.id || '0', 10);
    const name = row?.dataset.name || row?.querySelector('strong')?.textContent || '';
    if (id) openMoveModal(id, name);
  }
  async function renameAccountById(id) {
    const anyRow = document.querySelector(`.account-row[data-id='${id}']`);
    const current = anyRow?.dataset.name || anyRow?.querySelector('strong')?.textContent || '';
    const newName = prompt('Rename account to:', current);
    if (!newName || newName.trim() === '' || newName.trim() === current) return;
    const res = await postJSON(`/accounting/account/rename/${id}`, { name: newName.trim() });
    if (res && res.ok) {
      document.querySelectorAll(`.account-row[data-id='${id}']`).forEach(el => {
        el.dataset.name = newName.trim();
        const strong = el.querySelector('strong'); if (strong) strong.textContent = newName.trim();
      });
      document.querySelectorAll('.in-folder-panel').forEach(panel => resortNodeList(panel));
      const notin = document.getElementById('notin-list'); if (notin) resortNodeList(notin);
      const accl = document.getElementById('acc-list'); if (accl) resortNodeList(accl);
    }
  }
  async function renameAccountFromButton(btn) { const row = btn.closest('.account-row'); const id = parseInt(row?.dataset.id || '0', 10); if (id) await renameAccountById(id); }

  // Dropdown portal (outside scroll containers)
  let openPortal = null;
  let openAnchor = null;
  function closePortal(){
    if (openPortal && openPortal.parentNode) openPortal.parentNode.removeChild(openPortal);
    openPortal = null;
    openAnchor = null;
  }
  function openDropdownPortal(anchorBtn, items){
    closePortal();
    const rect = anchorBtn.getBoundingClientRect();
    const div = document.createElement('div');
    div.className = 'dropdown-portal';
    const left = Math.max(8, Math.min(window.innerWidth - 200, rect.right - 160));
    div.style.left = left + 'px';
    div.style.top = (rect.bottom + 6) + 'px';
    for (const it of items){
      const b = document.createElement('button');
      b.className = 'menu-item';
      b.innerHTML = it.html;
      b.addEventListener('click', () => { closePortal(); it.onClick && it.onClick(); });
      div.appendChild(b);
    }
    document.body.appendChild(div);
    openPortal = div;
    openAnchor = anchorBtn;
  }
  document.addEventListener('click', (e) => { if (!e.target.closest('.dropdown-portal') && !e.target.closest('.kebab-btn')) closePortal(); });
  function toggleRowMenu(btn){
    if (openPortal && openAnchor === btn) { closePortal(); return; }
    const row = btn.closest('.account-row'); if (!row) return;
    const id = parseInt(row.dataset.id || '0', 10);
    const inAccountsView = !!row.closest('#accounts-view');
    const items = [];
    items.push({ html: '<i class="fa fa-pen"></i> Rename', onClick: () => renameAccountById(id) });
    if (!inAccountsView) items.push({ html: '<i class="fa fa-unlink"></i> <span style="color:#b22222;">Unassign</span>', onClick: () => unassignAccount(id) });
    if (inAccountsView) items.push({ html: '<i class="fa fa-trash"></i> <span style="color:#b22222;">Delete</span>', onClick: () => deleteAccountById(id) });
    openDropdownPortal(btn, items);
  }

  async function deleteAccountById(id){
    if (!id) return;
    if (!confirm('Delete this account?')) return;
    try{
      const res = await fetch(`/accounting/account/delete/${id}`, { method:'POST', headers: { 'Content-Type':'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify({}) });
      if (!res.ok) return;
      document.querySelectorAll(`.account-row[data-id='${id}']`).forEach(el => el.remove());
      const notin = document.querySelector(`#notin-list .account-row[data-id='${id}']`); if (notin) notin.remove();
      document.querySelectorAll(`.in-folder-panel .account-row[data-id='${id}']`).forEach(el => el.remove());
    }catch(e){ console.error(e); }
  }
  async function toggleFolderMenu(btn){
    if (openPortal && openAnchor === btn) { closePortal(); return; }
    const el = btn.closest('.folder-item'); if (!el) return;
    const id = parseInt(el.dataset.id || '0', 10);
    const nameLabel = el.querySelector('.folder-name[data-label]');
    const input = el.querySelector('.rename-input');
    const items = [
      { html: '<i class="fa fa-pen"></i> Rename', onClick: () => { if (input && nameLabel){ input.style.display='block'; nameLabel.style.display='none'; input.value = nameLabel.textContent.trim(); input.focus(); } } },
      { html: '<i class="fa fa-trash"></i> <span style="color:#b22222;">Delete</span>', onClick: async () => {
        if (!confirm('Delete folder? Accounts inside will move to Unassigned.')) return;
        try{
          const res = await fetch(`/accounting/category/delete/${id}`, { method:'POST', headers:{ 'Content-Type':'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify({}) });
          if (res.ok){ el.remove(); const opt = document.querySelector(`#acc-folder-filter option[value='${id}']`); if (opt) opt.remove(); const modalItem = document.querySelector(`#modal .folder-list .folder-item[data-id='${id}']`); if (modalItem) modalItem.remove(); const panel = document.querySelector(`.in-folder-panel[data-folder-id='${id}']`); if (panel) panel.remove(); delete categoryMap[id]; delete folderColorMap[id]; filterNotInFolderList(); if (selectedFolderId === id) deselectFolder(); }
        }catch(err){ console.error(err); }
      } }
    ];
    openDropdownPortal(btn, items);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const storedView = localStorage.getItem('accountingView') || 'folders';
    showView(storedView);
    if (storedView === 'journal' && typeof window.ensureJournalLoaded === 'function') {
      window.ensureJournalLoaded();
    }
    if (storedView === 'receivables' && typeof window.initReceivableDebtUI === 'function') {
      window.initReceivableDebtUI();
    }
    const btnF = document.getElementById('btn-view-folders'); if (btnF) btnF.addEventListener('click', () => showView('folders'));
    const btnA = document.getElementById('btn-view-accounts'); if (btnA) btnA.addEventListener('click', () => showView('accounts'));
    const btnJ = document.getElementById('btn-view-journal'); if (btnJ) btnJ.addEventListener('click', () => { showView('journal'); if (typeof window.ensureJournalLoaded === 'function') window.ensureJournalLoaded(); });
    const btnT = document.getElementById('btn-view-trial'); if (btnT) btnT.addEventListener('click', () => showView('trial'));
    const btnR = document.getElementById('btn-view-receivables'); if (btnR) btnR.addEventListener('click', () => showView('receivables'));
    const clearBtn = document.getElementById('btn-clear-selection'); if (clearBtn) clearBtn.addEventListener('click', () => deselectFolder());

    const colors = ['#ff6b6b','#4dabf7','#51cf66','#845ef7','#ffa94d','#f06595','#20c997','#ffd43b'];
    const icons = ['fa-wallet','fa-piggy-bank','fa-building-columns','fa-credit-card','fa-coins','fa-chart-line','fa-sack-dollar','fa-box-archive'];
    document.querySelectorAll('.folder-list.sidebar .folder-item').forEach((el, idx) => {
      el.addEventListener('click', (ev) => {
        if (ev.target.closest('.folder-actions') || ev.target.closest('.icon-btn')) return;
        const id = parseInt(el.dataset.id,10);
        if (selectedFolderId === id) { deselectFolder(); } else { selectFolder(id); }
      });
      const color = colors[idx % colors.length];
      el.style.setProperty('--folder-color', color);
      const iconEl = el.querySelector('.folder-icon i'); if (iconEl) iconEl.classList.add(icons[idx % icons.length]);
      const id = parseInt(el.dataset.id,10); folderColorMap[id] = color;
      // Allow dropping account rows onto folders to move them
      el.addEventListener('dragover', (e) => { if (dragItem && dragItem.type==='account') { e.preventDefault(); el.classList.add('drop-target'); } });
      el.addEventListener('dragleave', () => el.classList.remove('drop-target'));
      el.addEventListener('drop', async (e) => {
        e.preventDefault(); el.classList.remove('drop-target');
        if (!dragItem || dragItem.type!=='account') return;
        try { await postJSON('/accounting/account/move', { account_id: dragItem.id, category_id: id, order: 9999 }); afterMoveUpdate(dragItem.id, id); } catch(err){ console.error(err); } finally { dragItem = null; }
      });
    });
    document.querySelectorAll('#modal .folder-list .folder-item').forEach((el, idx) => {
      const colors2 = ['#ff6b6b','#4dabf7','#51cf66','#845ef7','#ffa94d','#f06595','#20c997','#ffd43b'];
      const icons2 = ['fa-wallet','fa-piggy-bank','fa-building-columns','fa-credit-card','fa-coins','fa-chart-line','fa-sack-dollar','fa-box-archive'];
      el.style.setProperty('--folder-color', colors2[idx % colors2.length]);
      const iconEl = el.querySelector('.folder-icon i'); if (iconEl) iconEl.classList.add(icons2[idx % icons2.length]);
    });

    const lf = localStorage.getItem('lastFolderId');
    if (lf) { const exists = document.querySelector(`.folder-item[data-id='${lf}']`); if (exists) selectFolder(parseInt(lf,10)); }

    document.querySelectorAll('#folders-view .account-row[draggable="true"]').forEach(el => {
      el.addEventListener('dragstart', onDragStart);
      el.addEventListener('dragend', onDragEnd);
    });
    document.querySelectorAll('.account-list.dropzone').forEach(list => {
      list.addEventListener('dragover', onDragOverList);
      list.addEventListener('dragleave', onDragLeaveList);
      list.addEventListener('drop', onDropToList);
    });

    document.querySelectorAll('.in-folder-panel').forEach(panel => resortNodeList(panel));
    const notin = document.getElementById('notin-list'); if (notin) resortNodeList(notin);
    const accl = document.getElementById('acc-list'); if (accl) resortNodeList(accl);
    sortSidebarFoldersAlpha();
    bindSelectionHandlers(); updateSelectedCount();

    const s1 = document.getElementById('notin-search'); if (s1) s1.addEventListener('input', filterNotInFolderList);
    const s2 = document.getElementById('acc-search'); if (s2) s2.addEventListener('input', filterAccountsView);
    const c1 = document.getElementById('acc-only-uncat'); if (c1) c1.addEventListener('change', filterAccountsView);
    const f1 = document.getElementById('acc-folder-filter'); if (f1) f1.addEventListener('change', filterAccountsView);

    const modalClose = document.getElementById('modal-close'); if (modalClose) modalClose.addEventListener('click', () => closeMoveModal());

    const paneMid = document.getElementById('pane-in-folder'); const paneRight = document.getElementById('pane-notin');
    if (paneMid) paneMid.style.display = 'none'; if (paneRight) paneRight.style.display = 'none';
    updateAllBadges();
  });

  function sortSidebarFoldersAlpha(){
    const ul = document.querySelector('.folder-list.sidebar'); if (!ul) return;
    const items = Array.from(ul.querySelectorAll('.folder-item'));
    items.sort((a,b) => {
      const an = (a.querySelector('.folder-name[data-label]')?.textContent || '').trim().toLowerCase();
      const bn = (b.querySelector('.folder-name[data-label]')?.textContent || '').trim().toLowerCase();
      if (an < bn) return -1; if (an > bn) return 1; return 0;
    });
    items.forEach(li => ul.appendChild(li));
  }

  // Expose some functions to global for inline handlers
  window.postJSON = postJSON;
  window.addCategory = addCategory;
  window.moveToSelectedFolder = moveToSelectedFolder;
  window.unassignAccount = unassignAccount;
  window.openMoveModal = openMoveModal;
  window.closeMoveModal = closeMoveModal;
  window.modalAddFolder = modalAddFolder;
  window.modalMoveTo = modalMoveTo;
  window.modalMoveToBulk = modalMoveToBulk;
  window.openMoveModalFromButton = openMoveModalFromButton;
  window.renameAccountFromButton = renameAccountFromButton;
  window.deleteAccountFromButton = deleteAccountFromButton;
  window.toggleRowMenu = toggleRowMenu;
  window.toggleFolderMenu = toggleFolderMenu;
  // Expose color map so TB scripts can reuse the same colors
  window.folderColorMap = folderColorMap;
  // Expose sort so template can invoke after rename
  window.sortSidebarFoldersAlpha = sortSidebarFoldersAlpha;
})();
