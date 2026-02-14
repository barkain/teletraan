/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static HTML export for Tauri desktop builds.
  output: 'export',

  // The backend always runs on localhost:8000 inside the desktop app.
  env: {
    NEXT_PUBLIC_API_URL: 'http://127.0.0.1:8000',
    NEXT_PUBLIC_WS_URL: 'ws://127.0.0.1:8000/api/v1/chat',
  },

  // Disable image optimisation (requires a Node server, incompatible with static export).
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
