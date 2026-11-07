import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AuthGate } from "../components/auth-gate";

export const metadata: Metadata = {
  title: {
    default: "NEXUS — Personal Knowledge Intelligence",
    template: "NEXUS — %s",
  },
  applicationName: "NEXUS",
  description:
    "Ask your documents. Follow the evidence. A local-first document knowledge workspace.",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml", sizes: "any" },
      { url: "/favicon-32x32.png", type: "image/png", sizes: "32x32" },
      { url: "/favicon-16x16.png", type: "image/png", sizes: "16x16" },
    ],
    shortcut: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
};
export const viewport: Viewport = { themeColor: "#0d0f15" };

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
