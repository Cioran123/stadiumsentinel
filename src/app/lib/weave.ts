/**
 * Optional W&B Weave tracing for server routes. Without WANDB_API_KEY every call runs
 * untraced, so the demo never depends on W&B being reachable.
 */

type WeaveModule = typeof import("weave");
type AsyncFn<A extends unknown[], R> = (...args: A) => Promise<R>;

const globalAny = globalThis as unknown as {
  __weave?: Promise<WeaveModule | null>;
  __weaveOps?: Map<string, unknown>;
};

function getWeave(): Promise<WeaveModule | null> {
  if (!process.env.WANDB_API_KEY) return Promise.resolve(null);
  globalAny.__weave ??= (async () => {
    const weave = await import("weave");
    await weave.init(process.env.WEAVE_PROJECT ?? "stadium-sentinel");
    return weave;
  })().catch((err) => {
    console.warn("[weave] init failed; tracing disabled:", err instanceof Error ? err.message : err);
    return null;
  });
  return globalAny.__weave;
}

/** Run `fn` as a named Weave op when tracing is enabled. */
export async function traced<A extends unknown[], R>(name: string, fn: AsyncFn<A, R>, ...args: A): Promise<R> {
  const weave = await getWeave();
  if (!weave) return fn(...args);
  const ops = (globalAny.__weaveOps ??= new Map());
  let wrapped = ops.get(name) as AsyncFn<A, R> | undefined;
  if (!wrapped) {
    wrapped = weave.op(fn, { name }) as unknown as AsyncFn<A, R>;
    ops.set(name, wrapped);
  }
  return wrapped(...args);
}
