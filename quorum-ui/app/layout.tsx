import type { Metadata } from "next"
import "./globals.css"
import { Providers } from "@/app/providers"
import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

export const metadata: Metadata = {
  title: "Quorum",
  description: "Governed Analytics Review Board",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <body>
        <Providers>
          <div className="flex min-h-screen">
            <AppSidebar />
            <main className="flex-1 p-6 max-w-6xl mx-auto w-full"><AppHeader />{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  )
}
