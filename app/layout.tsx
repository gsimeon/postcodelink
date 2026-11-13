import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PostcodeLink Nigeria",
  description: "Postcode-aware delivery operations for Nigerian businesses."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
