/** Live save watching (Chromium): pick the Savegames/Story folder and
 *  re-parse whenever the game writes a new or updated .lsv. Read-only. */

interface DirectoryPickerOptions {
  id?: string;
  mode?: 'read' | 'readwrite';
}

declare global {
  interface Window {
    showDirectoryPicker?(options?: DirectoryPickerOptions): Promise<FileSystemDirectoryHandle>;
  }
  // lib.dom lacks the directory async iterator (WICG File System Access).
  interface FileSystemDirectoryHandle {
    entries(): AsyncIterableIterator<[string, FileSystemDirectoryHandle | FileSystemFileHandle]>;
  }
}

export interface WatchCallbacks {
  onSave(file: File): void;
  onStatus(text: string): void;
}

const POLL_MS = 3000;

let timer: ReturnType<typeof setInterval> | null = null;

export const watchSupported = (): boolean => typeof window.showDirectoryPicker === 'function';

export const isWatching = (): boolean => timer !== null;

export function stopWatching(): void {
  if (timer !== null) clearInterval(timer);
  timer = null;
}

/** All .lsv files at depth ≤2 (Story/<SaveName>/<SaveName>.lsv, or a single
 *  save folder picked directly). */
async function findSaves(
  dir: FileSystemDirectoryHandle,
  depth = 0,
): Promise<[string, FileSystemFileHandle][]> {
  const out: [string, FileSystemFileHandle][] = [];
  for await (const [name, handle] of dir.entries()) {
    if (handle.kind === 'file' && name.toLowerCase().endsWith('.lsv')) {
      out.push([name, handle as FileSystemFileHandle]);
    } else if (handle.kind === 'directory' && depth < 2) {
      for (const [sub, h] of await findSaves(handle as FileSystemDirectoryHandle, depth + 1)) {
        out.push([`${name}/${sub}`, h]);
      }
    }
  }
  return out;
}

/** Returns false if the user cancelled the picker. */
export async function startWatching(cb: WatchCallbacks): Promise<boolean> {
  const dir = await window.showDirectoryPicker!({ id: 'bg3-saves', mode: 'read' }).catch(
    () => null,
  );
  if (!dir) return false;
  stopWatching();

  const seen = new Map<string, number>();
  const pending = new Map<string, number>();

  // Parse the newest existing save right away; everything else counts as seen.
  const initial = await findSaves(dir);
  let newest: [string, File] | null = null;
  for (const [path, handle] of initial) {
    const f = await handle.getFile();
    seen.set(path, f.lastModified);
    if (!newest || f.lastModified > newest[1].lastModified) newest = [path, f];
  }
  cb.onStatus(`Watching ${dir.name} (${initial.length} save${initial.length === 1 ? '' : 's'}).`);
  if (newest) cb.onSave(newest[1]);

  const poll = async (): Promise<void> => {
    for (const [path, handle] of await findSaves(dir)) {
      const f = await handle.getFile().catch(() => null);
      if (!f || seen.get(path) === f.lastModified) continue;
      // A save mid-write changes between polls; parse only once it settles.
      if (pending.get(path) === f.lastModified) {
        pending.delete(path);
        seen.set(path, f.lastModified);
        cb.onSave(f);
      } else {
        pending.set(path, f.lastModified);
      }
    }
  };

  timer = setInterval(() => {
    void poll().catch(() => {
      // Folder went away or permission revoked; stop quietly.
      stopWatching();
      cb.onStatus('Stopped watching: the folder is no longer readable.');
    });
  }, POLL_MS);
  return true;
}
