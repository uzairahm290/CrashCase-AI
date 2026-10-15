// Proxies /api/* to the FastAPI service. The target is read at request time (API_URL),
// so the same image runs locally, in docker-compose and on ECS without a rebuild.
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const API_URL = () => process.env.API_URL ?? "http://localhost:8000";
const HOP_BY_HOP = ["host", "connection", "content-length", "transfer-encoding", "accept-encoding"];

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = `${API_URL()}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers(req.headers);
  HOP_BY_HOP.forEach((h) => headers.delete(h));

  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half"; // stream multipart uploads straight through
  }

  try {
    const res = await fetch(url, init);
    const out = new Headers(res.headers);
    out.delete("content-encoding");
    out.delete("content-length");
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return Response.json({ detail: "The claims service is not reachable." }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
