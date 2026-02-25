/**
 * Raspberry Pi Smart Drive - Main Client Script
 * Versión: Bucle Secuencial Estricto + UI de Inbox Vacio Correcta
 */

document.addEventListener("DOMContentLoaded", function() {
    initTreeCounts();
    fetchAndRenderFolders();
});

const form = document.getElementById('upload-form');
const dialog = document.getElementById('moveDialog');
let archivoActual = ""; 
let draggedItemPath = null; 
let draggedItemZone = null;

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

        const boton = form.querySelector('button');
        boton.disabled = true;

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
            const resCheck = await fetch(`/upload_status?filename=${encodeURIComponent(file.name)}`);
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
            const res = await fetch("/upload_chunk", { method: "POST", body: formData });
            if (!res.ok) throw new Error(`Error HTTP ${res.status}`);
            
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
    await finalizarSubida(file.name);
}

async function finalizarSubida(filename, action = 'check') {
    const formFinish = new FormData();
    formFinish.append("filename", filename);
    formFinish.append("action", action); 

    const res = await fetch("/upload_finish", { method: "POST", body: formFinish });

    if (res.status === 409) {
        return finalizarSubida(filename, 'rename'); // Auto-rename en colas
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
        const res = await fetch('/all-folders');
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
async function recargarArbol() {
    try {
        if (typeof closeActionMenus === 'function') closeActionMenus();
        const openPaths = new Set();
        document.querySelectorAll('#file-tree-root details[open] > summary').forEach(summary => {
            const path = summary.getAttribute('data-folder');
            if (path) openPaths.add(path);
        });

        const res = await fetch('/tree-html'); // Usamos el endpoint fragmentado
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
// 3. MOVIMIENTOS, DROP Y BORRADO (CORREGIDO INBOX VACIO)
// ==========================================

window.confirmarMover = async function() {
    const destino = document.getElementById('folderSelect').value;
    if (!destino || destino.includes("--")) return alert("Destino inválido");
    
    try {
        const res = await fetch('/move', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({ source_path: archivoActual, source_zone: 'inbox', destination_folder: destino }) 
        });
        
        const data = await res.json();
        if (res.ok && !data.error) { 
            dialog.close(); 
            const row = document.querySelector(`tr[data-filepath="${CSS.escape(archivoActual)}"][data-zone="inbox"]`);
            
            // CORREGIDO: Usar helper para mostrar "Inbox vacío"
            eliminarFilaInbox(row);
            
            await recargarArbol();
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
        const res = await fetch('/move', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_path: draggedItemPath, source_zone: draggedItemZone, destination_folder: destinationFolder }) 
        });
        const data = await res.json();
        if (res.ok && !data.error) {
            if (draggedItemZone === 'inbox') {
                const row = document.querySelector(`tr[data-filepath="${CSS.escape(draggedItemPath)}"][data-zone="inbox"]`);
                
                // CORREGIDO: Usar helper
                eliminarFilaInbox(row);
            }
            await recargarArbol();
        } else { alert("Error: " + (data.error || "Desconocido")); }
    } catch (error) { alert("Error de red."); }
};

window.borrarArchivo = async function(nombre) { if (confirm("¿Eliminar " + nombre + "?")) await ejecutarBorrado('inbox', nombre); };
window.borrarCatalogado = async function(ruta) { if (confirm("¿Eliminar del catálogo?")) await ejecutarBorrado('catalog', ruta); };

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
        actions.push({ label: 'Descargar ZIP', danger: false, handler: () => descargarZip(itemPath) });
        actions.push({ label: 'Renombrar', danger: false, handler: () => renombrarCarpeta(itemPath) });
        if (canDelete) {
            actions.push({ label: 'Borrar', danger: true, handler: () => borrarCarpeta(itemPath) });
        }
    } else if (menuType === 'catalog-file') {
        actions.push({ label: 'Descargar', danger: false, handler: () => descargarArchivo(`/data/files/${itemPath}`) });
        actions.push({ label: 'Abrir', danger: false, handler: () => abrirArchivo(`/data/files/${itemPath}`) });
        actions.push({ label: 'Renombrar', danger: false, handler: () => renombrarCatalogado(itemPath) });
        actions.push({ label: 'Borrar', danger: true, handler: () => borrarCatalogado(itemPath) });
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

async function ejecutarBorrado(zona, ruta) {
    try {
        const res = await fetch(`/delete/${zona}/${encodeURIComponent(ruta)}`, { method: 'DELETE' });
        if (res.ok) {
            if (zona === 'inbox') {
                const row = document.querySelector(`tr[data-filepath="${CSS.escape(ruta)}"][data-zone="inbox"]`);
                
                // CORREGIDO: Usar helper
                eliminarFilaInbox(row);
            } else { await recargarArbol(); }
        } else { const data = await res.json(); alert("Error: " + data.detail); }
    } catch (error) { alert("Error de conexión"); }
}

window.handleDragStart = function(event) { draggedItemPath = event.target.getAttribute('data-filepath'); draggedItemZone = event.target.getAttribute('data-zone'); event.target.style.opacity = '0.4'; };
window.allowDrop = function(e) { e.preventDefault(); e.currentTarget.classList.add('drag-over'); };
window.handleDragLeave = function(e) { e.currentTarget.classList.remove('drag-over'); };
document.addEventListener("dragend", function(e) { if(e.target) e.target.style.opacity = "1"; });

// NUEVAS FUNCIONES DE CARPETA
let currentSelectedFolder = "."; 

window.seleccionarCarpeta = function(event, path) {
    document.querySelectorAll('.folder-summary.selected').forEach(el => el.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
    currentSelectedFolder = path;
    const label = document.getElementById('selected-folder-name');
    if(label) label.innerText = path === "." ? "Raíz (/files/)" : path;
};

window.crearCarpetaMaestra = async function() {
    const nombre = prompt("Nombre de la nueva carpeta (dentro de " + currentSelectedFolder + "):");
    if (!nombre) return;
    const fullPath = currentSelectedFolder === "." ? nombre : `${currentSelectedFolder}/${nombre}`;
    try {
        const res = await fetch('/create-folder', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder_name: fullPath}) });
        if (res.ok) { 
            await recargarArbol();
            currentSelectedFolder = ".";
            document.getElementById('selected-folder-name').innerText = "Raíz (/files/)";
        } else { const d = await res.json(); alert("Error: " + d.error); }
    } catch (e) { alert("Error de red"); }
};

window.borrarCarpeta = async function(path) {
    if (!confirm(`¿Borrar carpeta vacía '${path}'?`)) return;
    try {
        const res = await fetch(`/delete-folder/${encodeURIComponent(path)}`, { method: 'DELETE' });
        if (res.ok) {
            await recargarArbol();
            currentSelectedFolder = ".";
            document.getElementById('selected-folder-name').innerText = "Raíz (/files/)";
        } else { 
            const d = await res.json(); alert("Error: " + d.detail); 
        }
    } catch (e) { alert("Error de red"); }
};

window.descargarZip = function(path) {
    window.open(`/download-folder/${encodeURIComponent(path)}`, '_blank');
};

window.descargarArchivo = function(url) {
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = '';
    enlace.rel = 'noopener';
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
};

window.abrirArchivo = function(url) {
    window.open(url, '_blank', 'noopener');
};

window.renombrarCarpeta = async function(path) {
    const nombreActual = path.split('/').pop();
    const nuevoNombre = prompt("Nuevo nombre de carpeta:", nombreActual);
    if (!nuevoNombre || nuevoNombre === nombreActual) return;

    try {
        const res = await fetch('/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ zone: 'folder', item_path: path, new_name: nuevoNombre })
        });
        const data = await res.json();
        if (res.ok) {
            await recargarArbol();
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

window.renombrarCatalogado = async function(rutaCodificada) {
    let ruta = rutaCodificada;
    try { ruta = decodeURIComponent(rutaCodificada); } catch (e) {}

    const nombreActual = ruta.split('/').pop();
    const nuevoNombre = prompt("Nuevo nombre del archivo:", nombreActual);
    if (!nuevoNombre || nuevoNombre === nombreActual) return;

    try {
        const res = await fetch('/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ zone: 'catalog', item_path: ruta, new_name: nuevoNombre })
        });
        const data = await res.json();
        if (res.ok) {
            await recargarArbol();
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
window.crearCarpeta = async function() {
    const nombre = document.getElementById('newFolderInput').value;
    if (!nombre) return;
    const res = await fetch('/create-folder', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder_name: nombre}) });
    if (res.ok) { alert("Carpeta creada"); document.getElementById('newFolderInput').value = ""; window.moverArchivo(archivoActual); }
};

window.moverArchivo = async function(nombre) {
    archivoActual = nombre; 
    document.getElementById('modalFilename').innerText = nombre;
    const res = await fetch('/scan-folders/' + encodeURIComponent(nombre)); 
    const data = await res.json();
    const select = document.getElementById('folderSelect'); 
    if (data.folders.length === 0) { select.innerHTML = ""; select.add(new Option("-- No hay carpetas --")); } 
    else { formatAndRenderFolders(select, data.folders, data.suggested); }
    dialog.showModal(); 
};

// --- Helper para gestionar el vaciado del Inbox ---
function eliminarFilaInbox(row) {
    if (!row) return;
    const tbody = row.parentElement;
    row.remove();
    if (tbody.children.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; padding: 30px; color: var(--text-muted);">Inbox vacío.</td></tr>`;
    }
}