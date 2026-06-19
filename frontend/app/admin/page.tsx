import { redirect } from "next/navigation";

/** Legacy / convenience alias — platform admin console lives under /admin-users. */
export default function AdminRootPage() {
  redirect("/admin-users");
}
