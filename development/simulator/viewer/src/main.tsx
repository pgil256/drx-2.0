import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { acceptSnapshot, readRecording } from "./session";
import type { Rig, Snapshot } from "./types";
import "./style.css";

const DeviceScene = lazy(() =>
  import("./scene/DeviceScene").then((module) => ({
    default: module.DeviceScene,
  })),
);

class ErrorBoundary extends React.Component<
  React.PropsWithChildren,
  { error: string }
> {
  state = { error: "" };
  static getDerivedStateFromError(error: Error) {
    return { error: error.message };
  }
  render() {
    return this.state.error ? (
      <div role="alert" className="error">
        Model could not load: {this.state.error}
      </div>
    ) : (
      this.props.children
    );
  }
}

function App() {
  const token = useRef(
    new URLSearchParams(location.hash.slice(1)).get("token") ?? "",
  );
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [rig, setRig] = useState<Rig | null>(null);
  const [connected, setConnected] = useState(false);
  const [stale, setStale] = useState(true);
  const [error, setError] = useState("");
  const [preset, setPreset] = useState("3/4");
  const [frames, setFrames] = useState<Snapshot[]>([]);
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [delay, setDelay] = useState(0);
  const [bias, setBias] = useState(0);
  const last = useRef(0);
  const previous = useRef<Snapshot | null>(null);
  const replaying = frames.length > 0;
  const displayed = replaying ? frames[frameIndex] : snapshot;
  const dashboardMode = displayed?.gui.cloud_mode === "dashboard";
  useEffect(() => {
    fetch("/models/rig.json")
      .then((response) => {
        if (!response.ok) throw new Error("Rig manifest is missing");
        return response.json();
      })
      .then(setRig)
      .catch((error) => setError(error.message));
    let socket: WebSocket | null = null;
    let retry = 0;
    let disposed = false;
    function connect() {
      if (disposed) return;
      socket = new WebSocket(
        `ws://${location.host}/api/stream?token=${encodeURIComponent(token.current)}`,
      );
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        try {
          const state: Snapshot = JSON.parse(event.data);
          if (acceptSnapshot(previous.current, state)) {
            previous.current = state;
            last.current = Date.now();
            setSnapshot(state);
          }
        } catch {
          setError("Received an invalid simulator snapshot");
        }
      };
      socket.onclose = () => {
        setConnected(false);
        retry = window.setTimeout(connect, 1500);
      };
    }
    connect();
    const timer = window.setInterval(
      () => setStale(Date.now() - last.current > 1200),
      250,
    );
    return () => {
      disposed = true;
      clearTimeout(retry);
      clearInterval(timer);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, []);
  useEffect(() => {
    if (!playing || !replaying) return;
    if (frameIndex >= frames.length - 1) {
      setPlaying(false);
      return;
    }
    const delayMs =
      ((frames[frameIndex + 1].sim_time - frames[frameIndex].sim_time) * 1000) /
      speed;
    const timer = window.setTimeout(
      () => setFrameIndex((index) => index + 1),
      Math.max(1, delayMs),
    );
    return () => clearTimeout(timer);
  }, [playing, replaying, frames, frameIndex, speed]);
  async function fault(name: string, value: boolean | number) {
    setError("");
    try {
      const response = await fetch("/api/fault", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Simulator-Token": token.current,
        },
        body: JSON.stringify({ name, value }),
      });
      if (!response.ok) throw new Error(await response.text());
    } catch (error) {
      setError(String(error));
    }
  }
  const mismatch =
    rig && displayed?.model_hash && rig.model_sha256 !== displayed.model_hash;
  const status = replaying
    ? "Recorded session"
    : stale
      ? "Feed unavailable"
      : displayed?.serial_connected
        ? "GUI connected"
        : "Waiting for GUI";
  const time = displayed ? Math.floor(displayed.sim_time - 1) : 0;
  const pose = displayed?.pose;
  const faultList = [
    ["jam_a", "Axial jam"],
    ["jam_b", "Horizontal jam"],
    ["jam_c", "Lateral jam"],
    ["freeze_a", "Freeze axial feedback"],
    ["freeze_b", "Freeze horizontal feedback"],
    ["freeze_c", "Freeze lateral feedback"],
    ["pressure_stale", "Disconnect load cell"],
    ["tare_failure", "Fail pressure baseline"],
    ["identity_mismatch", "Wrong firmware identity"],
  ];
  return (
    <main>
      <header>
        <div className="brand">
          <span className="brand-mark">DRX</span>
          <div>
            <strong>Device laboratory</strong>
            <small>
              {dashboardMode ? "Simulated hardware · Cloud dashboard mode" : "Desktop testing environment"}
            </small>
          </div>
        </div>
        <div className="session-status">
          <span className={`dot ${connected && !stale ? "live" : ""}`} />
          {status}
          <span className="pill">{dashboardMode ? "SIMULATION · CLOUD MODE" : "SIMULATION"}</span>
        </div>
      </header>
      <div className="workspace">
        <section className="stage" aria-label="3D device view">
          <div className="stage-top">
            <div>
              <span className="eyebrow">
                VIRTUAL DEVICE / {displayed?.profile ?? "CONNECTING"}
              </span>
              <h1>
                See the movement.
                <br />
                Test the response.
              </h1>
            </div>
            <nav aria-label="Camera angle">
              {["3/4", "Side", "Top"].map((view) => (
                <button
                  key={view}
                  className={preset === view ? "selected" : ""}
                  onClick={() => setPreset(view)}
                >
                  {view}
                </button>
              ))}
            </nav>
          </div>
          <div className="canvas">
            <ErrorBoundary>
              <Suspense
                fallback={<div className="loading">Loading device model…</div>}
              >
                {rig && !mismatch ? (
                  <DeviceScene snapshot={displayed} rig={rig} preset={preset} />
                ) : (
                  <div className="loading">
                    {mismatch
                      ? "Model version does not match this recording"
                      : "Loading device model…"}
                  </div>
                )}
              </Suspense>
            </ErrorBoundary>
          </div>
          <div className="stage-bottom">
            <span>Drag to orbit · Scroll to zoom</span>
            <span>Patient left − / right +</span>
            <span className="time">
              {Math.floor(time / 60)
                .toString()
                .padStart(2, "0")}
              :{(time % 60).toString().padStart(2, "0")}
            </span>
          </div>
          <div className="metrics">
            {[
              ["Axial travel", pose?.axial_inches, "in"],
              ["Horizontal", pose?.horizontal_degrees, "°"],
              ["Lateral", pose?.lateral_degrees, "°"],
              ["Physical load", pose?.force_lb, "lb"],
            ].map(([label, value, unit]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>
                  {typeof value === "number" ? value.toFixed(1) : "—"}
                  <small>{unit}</small>
                </strong>
              </div>
            ))}
          </div>
        </section>
        <aside>
          <section className="card">
            <span className="eyebrow">SESSION</span>
            <h2>
              {displayed?.gui.state?.replaceAll("_", " ") ??
                "Ready for the GUI"}
            </h2>
            <p>
              Use the KneeSpa window to set up and run treatment. This model
              follows the simulated hardware.
            </p>
            <div className="facts">
              <span>Controller</span>
              <b>
                {displayed?.backend === "native"
                  ? "Native firmware"
                  : "Firmware emulator"}
              </b>
              <span>Pressure baseline</span>
              <b>{displayed?.calibrated ? "Established" : "Required"}</b>
              <span>Pulse</span>
              <b>{displayed?.pulsing ? "Active" : "Off"}</b>
              <span>Leg length / FIT</span>
              <b>{pose?.fit_inches.toFixed(1) ?? "0.0"} in · estimated</b>
            </div>
            {displayed?.fault && (
              <div className="fault-banner" role="alert">
                {displayed.fault.replaceAll("_", " ")}
                <small>
                  Use the GUI's recovery flow after correcting the cause.
                </small>
              </div>
            )}
            {displayed?.releasing && (
              <p className="release">Physical stop: releasing load…</p>
            )}
          </section>
          <section className="card">
            <span className="eyebrow">PHYSICAL CONTROL</span>
            <button
              className={`stop ${displayed?.stop_pressed ? "engaged" : ""}`}
              disabled={replaying || stale}
              onClick={() => fault("physical_stop", !displayed?.stop_pressed)}
            >
              {displayed?.stop_pressed
                ? "Release physical stop"
                : "Press physical stop"}
            </button>
            <p className="hint">
              Models the device stop input, including when the GUI connection is
              down.
            </p>
          </section>
          <details className="card" open>
            <summary>Fault injection</summary>
            <fieldset disabled={replaying || stale}>
              {[
                ["drop_status", "Drop status stream"],
                ["drop_next_ack", "Drop next completion"],
                ["wrong_next_ack", "Wrong sequence on next completion"],
              ].map(([key, label]) => (
                <label className="toggle" key={key}>
                  <span>{label}</span>
                  <input
                    type="checkbox"
                    checked={Boolean(displayed?.link_faults?.[key])}
                    onChange={(event) => fault(key, event.target.checked)}
                  />
                </label>
              ))}
              <label className="toggle">
                <span>Fragment serial replies</span>
                <input
                  type="checkbox"
                  checked={Boolean(displayed?.link_faults?.fragment_bytes)}
                  onChange={(event) =>
                    fault("fragment_bytes", event.target.checked ? 3 : 0)
                  }
                />
              </label>
              <label className="toggle">
                <span>Fail local deliveries</span>
                <input
                  type="checkbox"
                  checked={Boolean(displayed?.local_deliveries_failed)}
                  onChange={(event) =>
                    fault("side_effect_failure", event.target.checked)
                  }
                />
              </label>
              {faultList.map(([key, label]) => (
                <label className="toggle" key={key}>
                  <span>{label}</span>
                  <input
                    type="checkbox"
                    checked={Boolean(displayed?.faults[key])}
                    onChange={(event) => fault(key, event.target.checked)}
                  />
                </label>
              ))}
              <label className="slider-label">
                Pressure bias <b>{bias} lb</b>
                <input
                  aria-label="Pressure bias"
                  type="range"
                  min="0"
                  max="110"
                  step="5"
                  value={bias}
                  onChange={(event) => {
                    setBias(+event.target.value);
                    fault("pressure_bias", +event.target.value);
                  }}
                />
              </label>
              <label className="slider-label">
                Reply delay <b>{delay} ms</b>
                <input
                  aria-label="Reply delay"
                  type="range"
                  min="0"
                  max="3000"
                  step="100"
                  value={delay}
                  onChange={(event) => {
                    setDelay(+event.target.value);
                    fault("delay_ms", +event.target.value);
                  }}
                />
              </label>
              <div className="actions">
                <button onClick={() => fault("disconnect", 10)}>
                  Disconnect for 10s
                </button>
                <button onClick={() => fault("corrupt_status", true)}>
                  Corrupt next status
                </button>
              </div>
            </fieldset>
          </details>
          <details className="card">
            <summary>Sensor feedback</summary>
            <div className="facts">
              <span>Axial / horizontal / lateral</span>
              <b>
                {displayed
                  ? `${displayed.sensors.a} / ${displayed.sensors.b} / ${displayed.sensors.c}`
                  : "—"}
              </b>
              <span>Reported pressure</span>
              <b>{displayed?.sensors.pressure_lb.toFixed(2) ?? "—"} lb</b>
              <span>Sample age</span>
              <b>{displayed?.sensors.age_ms.toFixed(0) ?? "—"} ms</b>
            </div>
          </details>
          <section className="card">
            <span className="eyebrow">RECORD & REVIEW</span>
            <div className="actions">
              <a
                className="button"
                href={`/api/recording?token=${encodeURIComponent(token.current)}`}
                download
              >
                Save session
              </a>
              <label className="button">
                Open recording
                <input
                  className="file-input"
                  aria-label="Open recording"
                  type="file"
                  accept=".jsonl"
                  onChange={async (event) => {
                    try {
                      const file = event.target.files?.[0];
                      if (file) {
                        const values = readRecording(await file.text());
                        if (!values.length)
                          throw new Error("No snapshots in recording");
                        setFrames(values);
                        setFrameIndex(0);
                        setPlaying(false);
                      }
                    } catch (error) {
                      setError(String(error));
                    }
                  }}
                />
              </label>
            </div>
            {replaying && (
              <div className="playback">
                <input
                  aria-label="Playback position"
                  type="range"
                  min="0"
                  max={frames.length - 1}
                  value={frameIndex}
                  onChange={(event) => setFrameIndex(+event.target.value)}
                />
                <div className="actions">
                  <button
                    onClick={() => {
                      if (frameIndex >= frames.length - 1) setFrameIndex(0);
                      setPlaying(!playing);
                    }}
                  >
                    {playing ? "Pause" : "Play"}
                  </button>
                  <select
                    aria-label="Playback speed"
                    value={speed}
                    onChange={(event) => setSpeed(+event.target.value)}
                  >
                    {[0.5, 1, 2, 5, 10].map((value) => (
                      <option key={value} value={value}>
                        {value}×
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => {
                      setFrames([]);
                      setPlaying(false);
                    }}
                  >
                    Return to live
                  </button>
                </div>
              </div>
            )}
            <p className="hint">
              Live testing runs at real speed. Recordings can be paused and
              replayed faster.
            </p>
          </section>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
        </aside>
      </div>
      <footer>
        <span>
          Synthetic fixture · Motion and load parameters are unmeasured
        </span>
        <span>
          {dashboardMode
            ? "Hardware recordings stay local · Patient sessions use the cloud dashboard"
            : "Model authored in Blender · All session data stays local"}
        </span>
      </footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
