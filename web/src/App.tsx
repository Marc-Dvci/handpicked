import { useCallback, useEffect, useState } from "react";
import { api, type Hand, type Samples, type Status } from "./api";
import Compare from "./Compare";
import Evidence from "./Evidence";
import Jewellers from "./Jewellers";

type Route = "compare" | "jewellers" | "evidence";

const ROUTES: { id: Route; hash: string; label: string; title: string }[] = [
  { id: "compare", hash: "#/", label: "Compare", title: "Handpicked" },
  { id: "jewellers", hash: "#/jewellers", label: "For jewellers", title: "For jewellers · Handpicked" },
  { id: "evidence", hash: "#/evidence", label: "Evidence", title: "Evidence · Handpicked" },
];

function routeOf(hash: string): Route {
  if (hash.startsWith("#/jewellers")) return "jewellers";
  if (hash.startsWith("#/evidence")) return "evidence";
  return "compare";
}

export type EvidenceData = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export default function App() {
  const [route, setRoute] = useState<Route>(routeOf(location.hash));
  const [status, setStatus] = useState<Status | null>(null);
  const [samples, setSamples] = useState<Samples | null>(null);
  const [evidence, setEvidence] = useState<EvidenceData | null>(null);
  const [hand, setHand] = useState<Hand | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const on = () => {
      setRoute(routeOf(location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  useEffect(() => {
    document.title = ROUTES.find((r) => r.id === route)!.title;
  }, [route]);

  const refreshStatus = useCallback(() => {
    api.status().then(setStatus).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshStatus();
    api.samples().then(setSamples).catch((e: Error) => setLoadError(e.message));
    api.evidence().then(setEvidence).catch(() => setEvidence({}));
  }, [refreshStatus]);

  return (
    <>
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>
        Skip to content
      </a>
      <header className="top">
        <div className="top-in">
          <a className="mark" href="#/">Handpicked<small>which diamond looks biggest on your hand</small></a>
          <nav className="nav" aria-label="Pages">
            {ROUTES.map((r) => (
              <a key={r.id} href={r.hash} aria-current={route === r.id ? "page" : undefined}>{r.label}</a>
            ))}
          </nav>
          <StatusLine s={status} />
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {loadError && <p className="error" role="alert">The server did not answer: {loadError}</p>}
        <div hidden={route !== "compare"}>
          <Compare samples={samples} hand={hand} setHand={setHand} status={status} evidence={evidence}
            onSpend={refreshStatus} />
        </div>
        <div hidden={route !== "jewellers"}>
          <Jewellers samples={samples} hand={hand} active={route === "jewellers"} />
        </div>
        <div hidden={route !== "evidence"}>
          <Evidence evidence={evidence} status={status} />
        </div>
      </main>
      <footer className="foot">
        <span>Handpicked · MIT licence · <a href="https://github.com/Marc-Dvci/handpicked">source</a></span>
        <span>Try-on: YouCam Ring Virtual Try-On API. Listing reader: Alibaba Cloud Model Studio.</span>
        <span>Sample hands are generated images of no real person. Sample prices: PriceScope, October 2026.</span>
      </footer>
    </>
  );
}

function StatusLine({ s }: { s: Status | null }) {
  if (!s) return <div className="status" aria-hidden="true">&nbsp;</div>;
  return (
    <div className="status">
      {s.mode === "live" ? (
        <>
          <b>Live</b> · YouCam Ring VTO
          {s.units_left != null && <> · {Math.round(s.units_left).toLocaleString("en-US")} units left</>}
          <br />this session {s.session_units} of {s.session_cap} units
          {s.median_seconds != null && <> · median {s.median_seconds.toFixed(1)} s</>}
        </>
      ) : (
        <>
          <b>Replay</b> · recorded YouCam try-ons
          <br />no key on this server; measurement and reading run live
        </>
      )}
    </div>
  );
}
