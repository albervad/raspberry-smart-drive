/**
 * Raspberry Pi Smart Drive - Main Client Script
 * Versión: Bucle Secuencial Estricto (Corrección de subida múltiple)
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

        // Convertimos a Array real para congelar la lista
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

        // --- BUCLE SECUENCIAL ESTRICTO ---
        // Usamos un contador manual para asegurar el orden
        for (let i = 0; i < totalFiles; i++) {
            const file = filesList[i];
            
            // Actualizamos texto GLOBAL para que veas qué pasa
            const statusText = document.getElementById('statusText');
            statusText.innerText = `[Archivo ${i + 1} de ${totalFiles}] Iniciando: ${file.name}`;
            document.getElementById('progressBar').style.width = "0%";
            
            console.log(`>>> Procesando archivo ${i + 1}/${totalFiles}: ${file.name}`);

            try {
                // 1. Subir este archivo y ESPERAR (await) a que termine
                await uploadSingleFile(file);
                
                // 2. Pequeña pausa de seguridad (0.5s) para que la Raspberry cierre el fichero
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
 * Devuelve una Promise que solo se resuelve cuando el servidor confirma el final.
 */
async function uploadSingleFile(file) {
    const CHUNK_SIZE = 64 * 1024 * 1024; // 64MB
    const progressBar = document.getElementById('progressBar');
    const statusText = document.getElementById('statusText');
    
    // 1. REANUDAR (Silencioso)
    let offset = 0;
    // Solo comprobamos si es > 50MB para ir rápido con los pequeños
    if (file.size > 50 * 1024 * 1024) { 
        try {
            const resCheck = await fetch(`/upload_status?filename=${encodeURIComponent(file.name)}`);
            if (resCheck.ok) {
                const dataCheck = await resCheck.json();
                offset = dataCheck.offset;
            }
        } catch (e) {}
    }

    // 2. BUCLE DE TROZOS
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
            
            // Actualizar barra
            const percent = Math.min((offset / file.size) * 100, 99);
            progressBar.style.width = percent + "%";
            statusText.innerText = `Subiendo ${file.name}... ${Math.round(percent)}%`;

        } catch (err) {
            console.warn("Reintentando chunk...", err);
            // Si falla, esperamos 2s y reintentamos el MISMO trozo (no sumamos offset)
            await new Promise(r => setTimeout(r, 2000));
        }
    }

    // 3. FINALIZAR
    statusText.innerText = `Finalizando ${file.name}...`;
    await finalizarSubida(file.name);
}

// Función recursiva para renombrar si existe conflicto
async function finalizarSubida(filename, action = 'check') {
    const formFinish = new FormData();
    formFinish.append("filename", filename);
    formFinish.append("action", action); 

    const res = await fetch("/upload_finish", { method: "POST", body: formFinish });

    // Si hay conflicto (409), renombramos automáticamente para no bloquear la cola
    if (res.status === 409) {
        console.log(`Conflicto con ${filename}, renombrando automáticamente...`);
        return finalizarSubida(filename, 'rename');
    }
    
    if (!res.ok) {
        const txt = await res.text();
        throw new Error("Fallo al finalizar: " + txt);
    }
    
    return await res.json();
}

// ==========================================
// 2. FUNCIONES AUXILIARES ÁRBOL (Idénticas)
// ==========================================

function initTreeCounts() {
    const folders = Array.from(document.querySelectorAll('.folder-node'));
    folders.reverse().forEach(folder => {
        let total = 0;
        
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

// Recargar árbol vía AJAX (para Drag & Drop)
async function recargarArbol() {
    try {
        const openPaths = new Set();
        document.querySelectorAll('#file-tree-root details[open] > summary').forEach(summary => {
            const path = summary.getAttribute('data-folder');
            if (path) openPaths.add(path);
        });

        const res = await fetch('/');
        const text = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'text/html');
        
        const newTree = doc.getElementById('file-tree-root');
        const currentTree = document.getElementById('file-tree-root');
        
        if (newTree && currentTree) {
            currentTree.replaceWith(newTree);
            
            openPaths.forEach(path => {
                const selector = `summary[data-folder="${CSS.escape(path)}"]`;
                const summaryToOpen = document.getElementById('file-tree-root').querySelector(selector);
                
                if (summaryToOpen) {
                    summaryToOpen.parentElement.open = true;
                }
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
                eliminarFilaInbox(row);
            }
            await recargarArbol();
        } else { alert("Error: " + (data.error || "Desconocido")); }
    } catch (error) { alert("Error de red."); }
};

window.borrarArchivo = async function(nombre) { if (confirm("¿Eliminar " + nombre + "?")) await ejecutarBorrado('inbox', nombre); };
window.borrarCatalogado = async function(ruta) { if (confirm("¿Eliminar del catálogo?")) await ejecutarBorrado('catalog', ruta); };

async function ejecutarBorrado(zona, ruta) {
    try {
        const res = await fetch(`/delete/${zona}/${encodeURIComponent(ruta)}`, { method: 'DELETE' });
        if (res.ok) {
            if (zona === 'inbox') {
                const row = document.querySelector(`tr[data-filepath="${CSS.escape(ruta)}"][data-zone="inbox"]`);
                eliminarFilaInbox(row);
            } else { await recargarArbol(); }
        } else { 
            const data = await res.json(); alert("Error: " + data.detail); 
        }
    } catch (error) { alert("Error de conexión"); }
}

window.handleDragStart = function(event) { draggedItemPath = event.target.getAttribute('data-filepath'); draggedItemZone = event.target.getAttribute('data-zone'); event.target.style.opacity = '0.4'; };
window.allowDrop = function(e) { e.preventDefault(); e.currentTarget.classList.add('drag-over'); };
window.handleDragLeave = function(e) { e.currentTarget.classList.remove('drag-over'); };
document.addEventListener("dragend", function(e) { if(e.target) e.target.style.opacity = "1"; });

window.crearCarpetaGlobal = async function() {
    const parentPath = document.getElementById('parentFolderSelect').value;
    const newFolderName = document.getElementById('newFolderName').value;
    if (!newFolderName) return alert("Nombre vacío.");
    const fullPath = parentPath === "." ? newFolderName : `${parentPath}/${newFolderName}`; 
    const res = await fetch('/create-folder', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({folder_name: fullPath}) });
    if (res.ok) { location.reload(); } else { alert("Error al crear."); }
};

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
    
    // Guardamos referencia al padre (tbody) antes de borrar la fila
    const tbody = row.parentElement;
    
    // Borramos la fila
    row.remove();

    // Verificamos si nos hemos quedado sin filas
    if (tbody.children.length === 0) {
        // Inyectamos el mensaje de "Inbox vacío"
        tbody.innerHTML = `
            <tr>
                <td colspan="3" style="text-align:center; padding: 30px; color: var(--text-muted);">
                    Inbox vacío.
                </td>
            </tr>`;
    }
}