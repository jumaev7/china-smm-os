"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Toaster } from "react-hot-toast";

import { useState } from "react";

import { I18nProvider } from "@/lib/I18nProvider";

import { AuthProvider } from "@/lib/auth-store";

import { AdminAuthProvider } from "@/lib/admin-auth-store";

import { DemoModeProvider } from "@/lib/demo-mode";



export function Providers({ children }: { children: React.ReactNode }) {

  const [queryClient] = useState(

    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } })

  );



  return (

    <QueryClientProvider client={queryClient}>

      <AuthProvider>

        <AdminAuthProvider>

          <I18nProvider>

            <DemoModeProvider>

              {children}

            </DemoModeProvider>

            <Toaster position="top-right" />

          </I18nProvider>

        </AdminAuthProvider>

      </AuthProvider>

    </QueryClientProvider>

  );

}

