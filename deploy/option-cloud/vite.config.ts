import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
export default defineConfig({base:'/',plugins:[react()],build:{outDir:'dist',sourcemap:false},test:{environment:'jsdom',maxWorkers:1,setupFiles:['./src/test/setup.ts']}});
