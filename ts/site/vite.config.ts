import { createReadStream, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';

// The anatomy page's sample save: a committed test fixture (the smallest one),
// served in dev and copied into the build so nothing is duplicated in git.
const SAMPLE = resolve(__dirname, '../../tests/fixtures/autosave_shadowheart_tutorial.lsv');

function sampleSave(): Plugin {
  return {
    name: 'sample-save',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split('?')[0] === '/sample.lsv') {
          res.setHeader('content-type', 'application/octet-stream');
          createReadStream(SAMPLE).pipe(res);
          return;
        }
        // Serve the clean URL in dev the way the production host does.
        if (req.url?.split('?')[0] === '/anatomy') req.url = '/anatomy.html';
        next();
      });
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'sample.lsv', source: readFileSync(SAMPLE) });
    },
  };
}

export default defineConfig({
  build: {
    target: 'es2022',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        anatomy: resolve(__dirname, 'anatomy.html'),
      },
    },
  },
  worker: { format: 'es' },
  plugins: [sampleSave()],
});
