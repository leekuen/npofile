import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";
import { Card } from "@/components/ui";

export const metadata: Metadata = { title: "註冊" };

export default function RegisterPage() {
  return (
    <div className="mx-auto max-w-sm space-y-4">
      <h1 className="font-display text-2xl font-extrabold text-ink-900">註冊</h1>
      <Card>
        <Suspense>
          <AuthForm mode="register" />
        </Suspense>
      </Card>
    </div>
  );
}
