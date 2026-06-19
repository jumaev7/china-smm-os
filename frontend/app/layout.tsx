import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

// Note: Inter font loaded via globals.css @import for sandbox compatibility.
// In Docker (with internet access), you can restore:
//   import { Inter } from "next/font/google";
//   const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-inter" });
// and add ${inter.variable} to body className.

export const metadata: Metadata = {
  title: "China SMM OS",
  description: "Internal social media management system for Chinese companies in Uzbekistan",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans bg-gray-50 text-gray-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
