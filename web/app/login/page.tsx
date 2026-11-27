import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";
import { Card } from "@/components/ui";

export const metadata: Metadata = { title: "登入" };

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-sm space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">登入</h1>
      <Card>
        <Suspense>
          <AuthForm mode="login" />
        </Suspense>
      </Card>
    </div>
  );
}
