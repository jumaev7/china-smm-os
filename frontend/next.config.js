/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8000" },
    ],
  },
  async redirects() {
    return [
      { source: "/buyer-search", destination: "/buyer-finder", permanent: false },
      { source: "/revenue-analytics", destination: "/analytics", permanent: false },
      { source: "/followups", destination: "/communications/followups", permanent: false },
      { source: "/templates", destination: "/communications/templates", permanent: false },
      { source: "/ai-assistant", destination: "/executive-copilot", permanent: false },
      { source: "/plans", destination: "/billing?tab=plans", permanent: false },
      { source: "/licenses", destination: "/billing?tab=licenses", permanent: false },
      { source: "/demo-management", destination: "/pilot-demo-mode", permanent: false },
      { source: "/platform-settings", destination: "/admin-settings", permanent: false },
    ];
  },
};

module.exports = nextConfig;
