export type Snapshot = {
  link_faults?: Record<string, boolean | number>;
  local_deliveries_failed?: boolean;
  schema: number;
  session_id: string;
  seq: number;
  sim_time: number;
  wall_time: number;
  serial_connected: boolean;
  backend: string;
  profile: string;
  model_hash: string | null;
  pose: {
    axial_inches: number;
    horizontal_degrees: number;
    lateral_degrees: number;
    fit_inches: number;
    force_lb: number;
  };
  sensors: {
    a: number;
    b: number;
    c: number;
    pressure_lb: number;
    age_ms: number;
  };
  targets: {
    a: number | null;
    b: number | null;
    c: number | null;
    pressure_lb: number;
  };
  pulsing: boolean;
  stop_pressed: boolean;
  releasing: boolean;
  fault: string | null;
  faults: Record<string, boolean | number>;
  calibrated: boolean;
  moving: boolean;
  gui: {
    cloud_mode?: "local" | "dashboard";
    state?: string;
    initialized?: boolean;
    baseline_valid?: boolean;
    connected?: boolean;
  };
};
export type Rig = {
  schema: number;
  model_sha256: string;
  units: string;
  joints: Record<
    string,
    { node: string; axis: [number, number, number]; sign: number }
  >;
};
