/** Hand a just-parsed save from the report page to /anatomy via IndexedDB.
 *  Written only when the user clicks through — never in the parse hot path. */

const DB = 'bg3-anatomy';
const STORE = 'handoff';
const KEY = 'last';

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function stashSave(name: string, bytes: ArrayBuffer): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).put({ name, bytes }, KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function takeSave(): Promise<{ name: string; bytes: ArrayBuffer } | null> {
  try {
    const db = await open();
    const rec = await new Promise<{ name: string; bytes: ArrayBuffer } | null>(
      (resolve, reject) => {
        const req = db.transaction(STORE, 'readonly').objectStore(STORE).get(KEY);
        req.onsuccess = () => resolve(req.result ?? null);
        req.onerror = () => reject(req.error);
      },
    );
    db.close();
    return rec;
  } catch {
    return null;
  }
}
