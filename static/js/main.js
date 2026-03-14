/**
 * Raspberry Pi Smart Drive - Main Client Script
 * Versión: Bucle Secuencial Estricto + UI de Inbox Vacio Correcta
 */

document.addEventListener("DOMContentLoaded", function() {
    initStorageUsageBar();
    initTabs();
    initTreeCounts();
    fetchAndRenderFolders();
    initSearch();
    initClipboard();
});

const form = document.getElementById('upload-form');
const dialog = document.getElementById('moveDialog');
const DRIVE_API_BASE = '/drive';
let currentFile = ""; 
let draggedItemPath = null; 
let draggedItemZone = null;

function apiPath(path) {
    const base = DRIVE_API_BASE.replace(/\/+$/, '');
    if (!path) {
        return base || '/';
    }
    const normalizedPath = String(path).replace(/^\/+/, '');
    return `${base}/${normalizedPath}`;
}

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta?.getAttribute('content') || '';
    return token.trim();
}

const rawFetch = window.fetch.bind(window);
window.fetch = function(resource, options = {}) {
    const requestOptions = { ...options };
    const method = String(requestOptions.method || 'GET').toUpperCase();

    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
        const csrfToken = getCsrfToken();
        if (csrfToken) {
            const headers = new Headers(requestOptions.headers || {});
            headers.set('X-CSRF-Token', csrfToken);
            requestOptions.headers = headers;
        }
    }

    return rawFetch(resource, requestOptions);
};

function initStorageUsageBar() {
    const usageBar = document.getElementById('storage-usage-bar');
    if (!usageBar) return;

    const rawPercent = usageBar.dataset.usagePercent || '0';
    const numericPercent = Number.parseFloat(rawPercent);
    const boundedPercent = Number.isFinite(numericPercent)
        ? Math.max(0, Math.min(numericPercent, 100))
        : 0;

    usageBar.style.width = `${boundedPercent}%`;
}

function initTabs() {
    const tabButtons = Array.from(document.querySelectorAll('.tab-btn'));
    const tabPanels = Array.from(document.querySelectorAll('.tab-panel'));
    if (!tabButtons.length || !tabPanels.length) return;

    const showTab = (tabName) => {
        tabButtons.forEach(button => {
            button.classList.toggle('active', button.dataset.tab === tabName);
        });

        tabPanels.forEach(panel => {
            panel.classList.toggle('active', panel.id === `tab-${tabName}`);
        });

        try {
            localStorage.setItem('drive_active_tab', tabName);
        } catch (error) {}
    };

    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = button.dataset.tab;
            if (!tabName) return;
            showTab(tabName);
        });
    });

    let initialTab = tabButtons[0]?.dataset.tab || 'files';
    try {
        const saved = localStorage.getItem('drive_active_tab');
        if (saved && tabButtons.some(button => button.dataset.tab === saved)) {
            initialTab = saved;
        }
    } catch (error) {}

    showTab(initialTab);
}

function initClipboard() {
    const textArea = document.getElementById('clipboard-text');
    const saveBtn = document.getElementById('clipboard-save-btn');
    const copyBtn = document.getElementById('clipboard-copy-btn');
    const pasteBtn = document.getElementById('clipboard-paste-btn');
    const refreshBtn = document.getElementById('clipboard-refresh-btn');

    if (!textArea || !saveBtn || !copyBtn || !pasteBtn || !refreshBtn) return;

    saveBtn.addEventListener('click', saveSharedClipboard);
    copyBtn.addEventListener('click', copyLocalClipboard);
    pasteBtn.addEventListener('click', pasteLocalClipboard);
    refreshBtn.addEventListener('click', loadSharedClipboard);

    loadSharedClipboard();
}

function setClipboardStatus(message, isError = false) {
    const status = document.getElementById('clipboard-status');
    if (!status) return;
    status.textContent = message;
    status.style.color = isError ? 'var(--danger-color)' : 'var(--text-muted)';
}

function formatClipboardDate(rawDate) {
    if (!rawDate) return 'Sin actualizaciones todavía.';
    const date = new Date(rawDate);
    if (Number.isNaN(date.getTime())) return 'Última actualización: fecha no disponible';
    return `Última actualización: ${date.toLocaleString()}`;
}

async function loadSharedClipboard() {
    const textArea = document.getElementById('clipboard-text');
    if (!textArea) return;

    setClipboardStatus('Cargando portapapeles...');

    try {
        const res = await fetch(apiPath('/clipboard'));
        if (!res.ok) throw new Error('No se pudo cargar');

        const data = await res.json();
        textArea.value = data.text || '';
        setClipboardStatus(formatClipboardDate(data.updated_at));
    } catch (error) {
        setClipboardStatus('No se pudo cargar el portapapeles compartido.', true);
    }
}

async function saveSharedClipboard() {
    const textArea = document.getElementById('clipboard-text');
    if (!textArea) return;

    setClipboardStatus('Guardando...');

    try {
        const res = await fetch(apiPath('/clipboard'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: textArea.value })
        });

        if (!res.ok) throw new Error('No se pudo guardar');

        const data = await res.json();
        textArea.value = data.text || '';
        setClipboardStatus(`${formatClipboardDate(data.updated_at)} · Guardado`);
    } catch (error) {
        setClipboardStatus('No se pudo guardar el portapapeles compartido.', true);
    }
}

async function copyLocalClipboard() {
    const textArea = document.getElementById('clipboard-text');
    if (!textArea) return;

    if (!navigator.clipboard || !navigator.clipboard.writeText) {
        setClipboardStatus('Este navegador no permite copiar automáticamente.', true);
        return;
    }

    try {
        await navigator.clipboard.writeText(textArea.value || '');
        setClipboardStatus('Texto copiado al portapapeles local.');
    } catch (error) {
        setClipboardStatus('No se pudo copiar al portapapeles local.', true);
    }
}

async function pasteLocalClipboard() {
    const textArea = document.getElementById('clipboard-text');
    if (!textArea) return;

    if (!navigator.clipboard || !navigator.clipboard.readText) {
        setClipboardStatus('Este navegador no permite pegar automáticamente.', true);
        return;
    }

    try {
        const text = await navigator.clipboard.readText();
        textArea.value = text;
        setClipboardStatus('Texto pegado desde portapapeles local. Pulsa Guardar para sincronizar.');
    } catch (error) {
        setClipboardStatus('No se pudo leer el portapapeles local.', true);
    }
}

function initSearch() {
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    const searchMode = document.getElementById('search-mode');

    if (!searchForm || !searchInput || !searchMode) return;

    searchForm.addEventListener('submit', async function(event) {
        event.preventDefault();
        const query = searchInput.value.trim();
        const mode = searchMode.value;
        await runSearch(query, mode);
    });
}

    async function runSearch(query, mode = 'both') {
    const resultsBox = document.getElementById('search-results');
    if (!resultsBox) return;

    if (query.length < 2) {
        resultsBox.style.display = 'block';
        resultsBox.innerHTML = `<p style="margin: 0; color: var(--text-muted);">Escribe al menos 2 caracteres para buscar.</p>`;
        return;
    }

    resultsBox.style.display = 'block';
    resultsBox.innerHTML = `<p style="margin: 0; color: var(--text-muted);">Buscando...</p>`;

    try {
        const res = await fetch(`${apiPath('/search')}?q=${encodeURIComponent(query)}&mode=${encodeURIComponent(mode)}`);
        if (!res.ok) throw new Error('Error de búsqueda');

        const data = await res.json();
        renderSearchResults(data.results || [], query);
    } catch (error) {
        resultsBox.innerHTML = `<p style="margin: 0; color: var(--danger-color);">No se pudo completar la búsqueda.</p>`;
    }
}

function renderSearchResults(results, query) {
    const resultsBox = document.getElementById('search-results');
    if (!resultsBox) return;

    resultsBox.innerHTML = '';

    if (!results.length) {
        resultsBox.innerHTML = `<p style="margin: 0; color: var(--text-muted);">Sin resultados para "${escapeHtml(query)}".</p>`;
        return;
    }

    const info = document.createElement('div');
    info.style.marginBottom = '8px';
    info.style.color = 'var(--text-muted)';
    info.style.fontSize = '0.9rem';
    info.textContent = `Resultados: ${results.length}`;
    resultsBox.appendChild(info);

    const tableWrap = document.createElement('div');
    tableWrap.className = 'table-responsive';

    const table = document.createElement('table');
    table.style.marginTop = '0';

    const thead = document.createElement('thead');
    thead.innerHTML = '<tr><th>Archivo</th><th>Zona</th><th>Coincidencia</th><th>Fragmento</th><th style="text-align:right;">Acciones</th></tr>';
    table.appendChild(thead);

    const tbody = document.createElement('tbody');

    results.forEach(item => {
        const tr = document.createElement('tr');

        const tdName = document.createElement('td');
        tdName.style.maxWidth = '220px';
        tdName.style.overflow = 'hidden';
        tdName.style.textOverflow = 'ellipsis';
        tdName.style.whiteSpace = 'nowrap';
        tdName.textContent = `${item.name} (${item.size})`;

        const tdZone = document.createElement('td');
        tdZone.textContent = item.zone === 'inbox' ? 'Inbox' : 'Catálogo';

        const tdMatch = document.createElement('td');
        tdMatch.textContent = item.match_type;

        const tdSnippet = document.createElement('td');
        tdSnippet.style.maxWidth = '280px';
        tdSnippet.style.overflow = 'hidden';
        tdSnippet.style.textOverflow = 'ellipsis';
        tdSnippet.style.whiteSpace = 'nowrap';
        tdSnippet.style.color = 'var(--text-muted)';
        tdSnippet.textContent = item.snippet || '-';

        const tdActions = document.createElement('td');
        tdActions.style.textAlign = 'right';
        const actionWrap = document.createElement('div');
        actionWrap.className = 'table-actions';

        const btnDownload = document.createElement('a');
        btnDownload.href = item.download_url;
        btnDownload.className = 'btn-action btn-small btn-secondary';
        btnDownload.setAttribute('download', item.name);
        btnDownload.title = 'Descargar';
        btnDownload.textContent = 'Descargar';

        const btnOpen = document.createElement('a');
        btnOpen.href = item.open_url;
        btnOpen.className = 'btn-action btn-small btn-secondary';
        btnOpen.target = '_blank';
        btnOpen.rel = 'noopener';
        btnOpen.title = 'Abrir';
        btnOpen.textContent = 'Abrir';

        actionWrap.appendChild(btnDownload);
        actionWrap.appendChild(btnOpen);
        tdActions.appendChild(actionWrap);

        tr.appendChild(tdName);
        tr.appendChild(tdZone);
        tr.appendChild(tdMatch);
        tr.appendChild(tdSnippet);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    tableWrap.appendChild(table);
    resultsBox.appendChild(tableWrap);
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ==========================================
// 1. LÓGICA DE SUBIDA (BUCLE STRICT)
// ==========================================
if (form) {
    form.addEventListener('submit', async function(event) {
        event.preventDefault();
        
        const fileInput = form.querySelector('input[type="file"]');
        if (fileInput.files.length === 0) return alert("Selecciona archivos");

        // Convertimos a Array real
        const filesList = Array.from(fileInput.files);
        const totalFiles = filesList.length;

        // UI INICIAL
        let progressBox = document.getElementById('upload-progress-box');
        if(!progressBox) {
            progressBox = document.createElement('div');
            progressBox.id = 'upload-progress-box';
            progressBox.className = 'section-box';
            progressBox.style.marginTop = '15px';
            progressBox.innerHTML = `
                <div class="flex-row" style="margin-bottom: 5px;">
                    <small id="statusText" style="color: var(--text-muted);">Preparando cola...</small>
                </div>
                <div style="background: #333; border-radius: 4px; overflow: hidden; height: 10px;">
                    <div id="progressBar" class="progress-bar" style="width: 0%;"></div>
                </div>`;
            form.appendChild(progressBox);
        }

        const submitButton = form.querySelector('button');
        submitButton.disabled = true;

        // --- BUCLE SECUENCIAL ---
        for (let i = 0; i < totalFiles; i++) {
            const file = filesList[i];
            const statusText = document.getElementById('statusText');
            statusText.innerText = `[Archivo ${i + 1} de ${totalFiles}] Iniciando: ${file.name}`;
            document.getElementById('progressBar').style.width = "0%";
            
            try {
                await uploadSingleFile(file);
                
                statusText.innerText = `[Archivo ${i + 1} de ${totalFiles}] Guardado. Esperando...`;
                await new Promise(r => setTimeout(r, 500));
                
            } catch (error) {
                console.error(`Error en ${file.name}:`, error);
                alert(`Error al subir ${file.name}. Se pasará al siguiente.`);
            }
        }

        // FIN TOTAL
        document.getElementById('statusText').innerText = "¡Cola completada! Recargando...";
        document.getElementById('progressBar').style.width = "100%";
        setTimeout(() => location.reload(), 1000);
    });
}

/**
 * Sube un solo archivo trozo a trozo.
 */
async function uploadSingleFile(file) {
    const CHUNK_SIZE = 64 * 1024 * 1024; // 64MB
    const progressBar = document.getElementById('progressBar');
    const statusText = document.getElementById('statusText');
    
    // 1. REANUDAR
    let offset = 0;
    if (file.size > 50 * 1024 * 1024) { 
        try {
            const resCheck = await fetch(`${apiPath('/upload_status')}?filename=${encodeURIComponent(file.name)}`);
            if (resCheck.ok) {
                const dataCheck = await resCheck.json();
                offset = dataCheck.offset;
            }
        } catch (e) {}
    }

    // 2. SUBIR TROZOS
    while (offset < file.size) {
        const chunk = file.slice(offset, offset + CHUNK_SIZE);
        const formData = new FormData();
        formData.append("file", chunk);
        formData.append("filename", file.name);
        formData.append("chunk_offset", offset);

        try {
            const res = await fetch(apiPath('/upload_chunk'), { method: "POST", body: formData });
            if (!res.ok) {
                if (res.status === 409) {
                    let payload = null;
                    try {
                        payload = await res.json();
                    } catch (error) {}

                    const expectedOffset = Number(payload?.detail?.expected_offset);
                    if (Number.isFinite(expectedOffset) && expectedOffset >= 0) {
                        offset = expectedOffset;
                        const percent = file.size > 0
                            ? Math.min((offset / file.size) * 100, 99)
                            : 0;
                        progressBar.style.width = percent + "%";
                        statusText.innerText = `Re-sincronizando ${file.name}... ${Math.round(percent)}%`;
                        continue;
                    }
                }

                throw new Error(`Error HTTP ${res.status}`);
            }
            
            offset += chunk.size;
            
            const percent = Math.min((offset / file.size) * 100, 99);
            progressBar.style.width = percent + "%";
            statusText.innerText = `Subiendo ${file.name}... ${Math.round(percent)}%`;

        } catch (err) {
            console.warn("Reintentando chunk...", err);
            await new Promise(r => setTimeout(r, 2000));
        }
    }

    // 3. FINALIZAR
    statusText.innerText = `Finalizando ${file.name}...`;
    await finishUpload(file.name);
}

async function finishUpload(filename, action = 'check') {
    const formFinish = new FormData();
    formFinish.append("filename", filename);
    formFinish.append("action", action); 

    const res = await fetch(apiPath('/upload_finish'), { method: "POST", body: formFinish });

    if (res.status === 409) {
        return finishUpload(filename, 'rename'); // Auto-rename en colas
    }
    if (!res.ok) {
        const txt = await res.text();
        throw new Error("Fallo al finalizar: " + txt);
    }
    return await res.json();
}

// ==========================================
// 2. FUNCIONES AUXILIARES ÁRBOL (CORREGIDO)
// ==========================================

function initTreeCounts() {
    const folders = Array.from(document.querySelectorAll('.folder-node'));
    folders.reverse().forEach(folder => {
        let total = 0;
        // Buscamos tabla responsive O directa
        const table = folder.querySelector(':scope > div > .table-responsive > table') || 
                      folder.querySelector(':scope > div > table');
                      
        if (table) { total += table.querySelectorAll('tr').length; }
        
        const subfolders = folder.querySelectorAll(':scope > div > .folder-node');
        subfolders.forEach(sub => { total += parseInt(sub.getAttribute('data-total') || 0); });
        
        folder.setAttribute('data-total', total);
        const span = folder.querySelector(':scope > summary .file-count');
        if (span) span.innerText = `(${total})`;
    });
}

async function fetchAndRenderFolders() {
    const select = document.getElementById('parentFolderSelect');
    if (!select) return; 
    try {
        const res = await fetch(apiPath('/all-folders'));
        const data = await res.json();
        formatAndRenderFolders(select, data.folders);
    } catch (error) { select.innerHTML = "<option value='.'>Error al cargar.</option>"; }
}

function formatAndRenderFolders(selectElement, folders, suggestedFolder = null) {
    selectElement.innerHTML = ""; 
    const processedFolders = folders.map(path => {
        let cleanedPath = path.startsWith('./') ? path.substring(2) : path;
        return { original: path, display: cleanedPath, sortKey: cleanedPath === '.' ? ' ' : cleanedPath };
    });
    processedFolders.sort((a, b) => a.sortKey.localeCompare(b.sortKey));
    processedFolders.forEach(folder => {
        const option = document.createElement('option');
        option.value = folder.original;
        let displayText = folder.display;
        if (folder.original === ".") displayText = "Raíz (/files/)"; 
        else {
            const parts = displayText.split('/');
            const level = parts.length - 1; 
            const indent = '— '.repeat(level); 
            displayText = indent + parts.pop(); 
        }
        if (suggestedFolder && folder.original === suggestedFolder) displayText += " (⭐ Sugerido)";
        option.text = displayText;
        option.defaultSelected = (folder.original === suggestedFolder);
        selectElement.add(option);
    });
}

// Recargar árbol vía AJAX manteniendo estado abierto
async function reloadTree() {
    try {
        if (typeof closeActionMenus === 'function') closeActionMenus();
        const openPaths = new Set();
        document.querySelectorAll('#file-tree-root details[open] > summary').forEach(summary => {
            const path = summary.getAttribute('data-folder');
            if (path) openPaths.add(path);
        });

        const res = await fetch(apiPath('/tree-html')); // Usamos el endpoint fragmentado
        if (!res.ok) throw new Error("Error fetching tree fragment");
        
        const html = await res.text();
        const currentTree = document.getElementById('file-tree-root');
        
        if (currentTree) {
            currentTree.outerHTML = html; // Reemplazamos el div entero
            
            // Restaurar estado abierto
            openPaths.forEach(path => {
                const selector = `summary[data-folder="${CSS.escape(path)}"]`;
                const summaryToOpen = document.getElementById('file-tree-root').querySelector(selector);
                if (summaryToOpen) summaryToOpen.parentElement.open = true;
            });
            initTreeCounts();
        }
    } catch (e) { 
        console.error("Error actualizando árbol:", e); 
    }
}

// ==========================================
// 3. MOVIMIENTOS, DROP Y BORRADO 
// ==========================================

window.confirmMove = async function() {
    const destination = document.getElementById('folderSelect').value;
    if (!destination || destination.includes("--")) return alert("Destino inválido");
    
    try {
        const res = await fetch(apiPath('/move'), { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({ source_path: currentFile, source_zone: 'inbox', destination_folder: destination }) 
        });
        
        const data = await res.json();
        if (res.ok && !data.error) { 
            dialog.close(); 
            const row = document.querySelector(`tr[data-filepath="${CSS.escape(currentFile)}"][data-zone="inbox"]`);
            removeInboxRow(row);
            
            await reloadTree();
        } else { alert("Error: " + (data.error || "Desconocido")); }
    } catch (error) { alert("Error de red."); }
};

window.handleDrop = async function(event) {
    event.preventDefault();
    event.currentTarget.classList.remove('drag-over');
    document.querySelectorAll('.draggable-file').forEach(el => el.style.opacity = '1');
    if (!draggedItemPath) return;
    let destinationFolder = event.currentTarget.getAttribute('data-folder');
    if (!destinationFolder) destinationFolder = "."; 
    
    try {
        const res = await fetch(apiPath('/move'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_path: draggedItemPath, source_zone: draggedItemZone, destination_folder: destinationFolder }) 
        });
        const data = await res.json();
        if (res.ok && !data.error) {
            if (draggedItemZone === 'inbox') {
                const row = document.querySelector(`tr[data-filepath="${CSS.escape(draggedItemPath)}"][data-zone="inbox"]`);
                removeInboxRow(row);
            }
            await reloadTree();
        } else { alert("Error: " + (data.error || "Desconocido")); }
    } catch (error) { alert("Error de red."); }
};

window.deleteInboxFile = async function(fileName) { if (confirm("¿Eliminar " + fileName + "?")) await runDelete('inbox', fileName); };
window.deleteCatalogFile = async function(path) { if (confirm("¿Eliminar del catálogo?")) await runDelete('catalog', path); };

let activeMenuTrigger = null;

function getGlobalMenuElement() {
    return document.getElementById('global-action-menu');
}

window.openActionMenu = function(event, triggerBtn) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    const sameTrigger = activeMenuTrigger === triggerBtn;
    closeActionMenus();
    if (sameTrigger) return;

    const menu = getGlobalMenuElement();
    if (!menu || !triggerBtn) return;

    const menuType = triggerBtn.dataset.menuType;
    const itemPath = triggerBtn.dataset.itemPath;
    const canDelete = triggerBtn.dataset.canDelete === '1';
    if (!menuType || !itemPath) return;

    const actions = [];
    if (menuType === 'folder') {
        actions.push({ label: 'Descargar ZIP', danger: false, handler: () => downloadZip(itemPath) });
        actions.push({ label: 'Renombrar', danger: false, handler: () => renameFolder(itemPath) });
        if (canDelete) {
            actions.push({ label: 'Borrar', danger: true, handler: () => deleteFolder(itemPath) });
        }
    } else if (menuType === 'catalog-file') {
        actions.push({ label: 'Descargar', danger: false, handler: () => downloadFile(`/drive/download/catalog/${itemPath}`) });
        actions.push({ label: 'Abrir', danger: false, handler: () => openFile(`/drive/open/catalog/${itemPath}`) });
        actions.push({ label: 'Renombrar', danger: false, handler: () => renameCatalogFile(itemPath) });
        actions.push({ label: 'Borrar', danger: true, handler: () => deleteCatalogFile(itemPath) });
    }

    menu.innerHTML = '';
    actions.forEach(action => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `menu-item${action.danger ? ' danger' : ''}`;
        button.textContent = action.label;
        button.addEventListener('click', function(e) {
            e.stopPropagation();
            closeActionMenus();
            action.handler();
        });
        menu.appendChild(button);
    });

    menu.style.display = 'block';
    positionGlobalMenu(triggerBtn, menu);
    activeMenuTrigger = triggerBtn;
};

window.openActionMenuFromTrigger = function(triggerBtn) {
    openActionMenu(window.event || null, triggerBtn);
    return false;
};

window.closeActionMenus = function() {
    const menu = getGlobalMenuElement();
    if (menu) {
        menu.style.display = 'none';
        menu.innerHTML = '';
    }
    activeMenuTrigger = null;
};

function positionGlobalMenu(triggerBtn, menu) {
    if (!triggerBtn || !menu) return;

    const triggerRect = triggerBtn.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const margin = 8;
    const gap = 6;

    let left = triggerRect.right - menuRect.width;
    if (left < margin) left = margin;
    if (left + menuRect.width > window.innerWidth - margin) {
        left = window.innerWidth - menuRect.width - margin;
    }

    let top = triggerRect.bottom + gap;
    if (top + menuRect.height > window.innerHeight - margin) {
        top = triggerRect.top - menuRect.height - gap;
    }
    if (top < margin) top = margin;

    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
}

async function runDelete(zone, path) {
    const rawPath = String(path ?? '');
    let decodedPath = rawPath;
    try {
        decodedPath = decodeURIComponent(rawPath);
    } catch (e) {
        decodedPath = rawPath;
    }

    const encodedPath = encodeURIComponent(decodedPath);

    try {
        const res = await fetch(`${apiPath('/delete')}/${zone}/${encodedPath}`, { method: 'DELETE' });
        if (res.ok) {
            if (zone === 'inbox') {
                const row = document.querySelector(`tr[data-filepath="${CSS.escape(decodedPath)}"][data-zone="inbox"]`);
                removeInboxRow(row);
            } else { await reloadTree(); }
        } else { const data = await res.json(); alert("Error: " + data.detail); }
    } catch (error) { alert("Error de conexión"); }
}

window.handleDragStart = function(event) { draggedItemPath = event.target.getAttribute('data-filepath'); draggedItemZone = event.target.getAttribute('data-zone'); event.target.style.opacity = '0.4'; };
window.allowDrop = function(e) { e.preventDefault(); e.currentTarget.classList.add('drag-over'); };
window.handleDragLeave = function(e) { e.currentTarget.classList.remove('drag-over'); };
document.addEventListener("dragend", function(e) { if(e.target) e.target.style.opacity = "1"; });

// NUEVAS FUNCIONES DE CARPETA
let currentSelectedFolder = "."; 

window.selectFolder = function(event, path) {
    document.querySelectorAll('.folder-summary.selected').forEach(el => el.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
    currentSelectedFolder = path;
    const label = document.getElementById('selected-folder-name');
    if(label) label.innerText = path === "." ? "Raíz (/files/)" : path;
};

window.createFolderAtSelection = async function() {
    const folderName = prompt("Nombre de la nueva carpeta (dentro de " + currentSelectedFolder + "):");
    if (!folderName) return;
    const fullPath = currentSelectedFolder === "." ? folderName : `${currentSelectedFolder}/${folderName}`;
    try {
        const res = await fetch(apiPath('/create-folder'), { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder_name: fullPath}) });
        if (res.ok) { 
            await reloadTree();
            currentSelectedFolder = ".";
            document.getElementById('selected-folder-name').innerText = "Raíz (/files/)";
        } else { const d = await res.json(); alert("Error: " + d.error); }
    } catch (e) { alert("Error de red"); }
};

window.deleteFolder = async function(path) {
    if (!confirm(`¿Borrar carpeta vacía '${path}'?`)) return;
    try {
        const res = await fetch(`${apiPath('/delete-folder')}/${encodeURIComponent(path)}`, { method: 'DELETE' });
        if (res.ok) {
            await reloadTree();
            currentSelectedFolder = ".";
            document.getElementById('selected-folder-name').innerText = "Raíz (/files/)";
        } else { 
            const d = await res.json(); alert("Error: " + d.detail); 
        }
    } catch (e) { alert("Error de red"); }
};

window.downloadZip = function(path) {
    window.open(`${apiPath('/download-folder')}/${encodeURIComponent(path)}`, '_blank');
};

window.downloadFile = function(url) {
    const link = document.createElement('a');
    link.href = url;
    link.download = '';
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
};

window.openFile = function(url) {
    window.open(url, '_blank', 'noopener');
};

window.renameFolder = async function(path) {
    const currentName = path.split('/').pop();
    const newName = prompt("Nuevo nombre de carpeta:", currentName);
    if (!newName || newName === currentName) return;

    try {
        const res = await fetch(apiPath('/rename'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ zone: 'folder', item_path: path, new_name: newName })
        });
        const data = await res.json();
        if (res.ok) {
            await reloadTree();
            currentSelectedFolder = ".";
            const label = document.getElementById('selected-folder-name');
            if (label) label.innerText = "Raíz (/files/)";
        } else {
            alert("Error: " + (data.detail || data.error || "No se pudo renombrar"));
        }
    } catch (e) {
        alert("Error de red");
    }
};

window.renameCatalogFile = async function(encodedPath) {
    let path = encodedPath;
    try { path = decodeURIComponent(encodedPath); } catch (e) {}

    const currentName = path.split('/').pop();
    const newName = prompt("Nuevo nombre del archivo:", currentName);
    if (!newName || newName === currentName) return;

    try {
        const res = await fetch(apiPath('/rename'), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ zone: 'catalog', item_path: path, new_name: newName })
        });
        const data = await res.json();
        if (res.ok) {
            await reloadTree();
        } else {
            alert("Error: " + (data.detail || data.error || "No se pudo renombrar"));
        }
    } catch (e) {
        alert("Error de red");
    }
};

document.addEventListener('click', function(e) {
    if (!e.target.closest('.action-menu') && !e.target.closest('#global-action-menu')) {
        closeActionMenus();
    }

    if (!e.target.closest('.folder-summary') && !e.target.closest('button')) {
        document.querySelectorAll('.folder-summary.selected').forEach(el => el.classList.remove('selected'));
        currentSelectedFolder = ".";
        const label = document.getElementById('selected-folder-name');
        if(label) label.innerText = "Raíz (/files/)";
    }
});

window.addEventListener('resize', function() {
    const menu = getGlobalMenuElement();
    if (menu && menu.style.display === 'block' && activeMenuTrigger) {
        positionGlobalMenu(activeMenuTrigger, menu);
    }
});

window.addEventListener('scroll', function() {
    const menu = getGlobalMenuElement();
    if (menu && menu.style.display === 'block' && activeMenuTrigger) {
        positionGlobalMenu(activeMenuTrigger, menu);
    }
}, true);

// OTRAS
window.createFolder = async function() {
    const folderName = document.getElementById('newFolderInput').value;
    if (!folderName) return;
    const res = await fetch(apiPath('/create-folder'), { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder_name: folderName}) });
    if (res.ok) { alert("Carpeta creada"); document.getElementById('newFolderInput').value = ""; window.moveFile(currentFile); }
};

window.moveFile = async function(fileName) {
    currentFile = fileName; 
    document.getElementById('modalFilename').innerText = fileName;
    const res = await fetch(apiPath('/scan-folders/' + encodeURIComponent(fileName))); 
    const data = await res.json();
    const select = document.getElementById('folderSelect'); 
    if (data.folders.length === 0) { select.innerHTML = ""; select.add(new Option("-- No hay carpetas --")); } 
    else { formatAndRenderFolders(select, data.folders, data.suggested); }
    dialog.showModal(); 
};

// --- Helper para gestionar el vaciado del Inbox ---
function removeInboxRow(row) {
    if (!row) return;
    const tbody = row.parentElement;
    row.remove();
    if (tbody.children.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; padding: 30px; color: var(--text-muted);">Inbox vacío.</td></tr>`;
    }
}