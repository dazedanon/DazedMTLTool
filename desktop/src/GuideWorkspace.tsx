import { useEffect, useRef, useState } from "react";
import { api } from "./bridge";

export default function GuideWorkspace({
  onNavigate,
}: {
  onNavigate: (page: string) => void;
}) {
  const [catalog, setCatalog] = useState<
    Awaited<ReturnType<typeof api.guideCatalog>>
  >([]);
  const [page, setPage] = useState<Awaited<
    ReturnType<typeof api.guidePage>
  > | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const article = useRef<HTMLElement>(null);
  const report = (error: unknown) =>
    setError(error instanceof Error ? error.message : String(error));
  async function open(identity: string, anchor = "") {
    setBusy(true);
    setError("");
    try {
      setPage(await api.guidePage(identity));
      requestAnimationFrame(() => {
        if (anchor)
          article.current
            ?.querySelector(`#${CSS.escape(decodeURIComponent(anchor))}`)
            ?.scrollIntoView();
        else article.current?.scrollIntoView({ block: "start" });
      });
    } catch (error) {
      report(error);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    api.guideCatalog().then(setCatalog).catch(report);
    open("welcome");
  }, []);
  return (
    <section className="guide-workspace">
      <div className="page-heading">
        <div>
          <p className="eyebrow">BUILT-IN GUIDE</p>
          <h1>A guide to your translation tools.</h1>
          <p>
            Shared documentation for RPG Maker, WOLF, AI helpers, playtesting,
            and recovery. Screenshots show the original interface.
          </p>
        </div>
      </div>
      <div className="actions guide-actions">
        <button className="primary" onClick={() => onNavigate("workflow")}>
          Open guided workflow
        </button>
        <button onClick={() => onNavigate("settings")}>Open settings</button>
        <button disabled={busy || !page} onClick={() => page && open(page.id)}>
          Refresh this page
        </button>
      </div>
      {error && (
        <p className="banner error" role="alert">
          {error}
        </p>
      )}
      <div className="library-layout">
        <nav className="library-list" aria-label="Guide articles">
          <label>
            Find an article
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          {catalog
            .filter(
              (item) =>
                !query ||
                item.title.toLowerCase().includes(query.toLowerCase()),
            )
            .map((item, index) =>
              item.type === "group" ? (
                <h2 key={index}>{item.title}</h2>
              ) : (
                <button
                  key={item.id}
                  disabled={busy}
                  aria-current={page?.id === item.id ? "page" : undefined}
                  onClick={() => open(item.id!)}
                >
                  {item.title}
                </button>
              ),
            )}
        </nav>
        <article
          className="guide-article"
          ref={article}
          aria-label={page?.title}
          onClick={(event) => {
            const link = (event.target as Element).closest("a");
            if (!link) return;
            event.preventDefault();
            const href = link.getAttribute("href") || "";
            if (href.startsWith("guide:")) {
              const [id, anchor] = href.slice(6).split("#");
              open(id, anchor);
            } else if (href.startsWith("#") && href.length > 1)
              article.current
                ?.querySelector(
                  `#${CSS.escape(decodeURIComponent(href.slice(1)))}`,
                )
                ?.scrollIntoView();
            else if (page?.external_links.includes(href))
              api.guideLink(href).catch(report);
          }}
          dangerouslySetInnerHTML={{
            __html: page?.html || "<p>Loading the guide…</p>",
          }}
        />
      </div>
    </section>
  );
}
