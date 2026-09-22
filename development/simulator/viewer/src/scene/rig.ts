import { Object3D, Quaternion, Vector3 } from "three";
import type { Rig, Snapshot } from "../types";

export function bindRig(scene: Object3D, rig: Rig) {
  const joints = Object.entries(rig.joints).map(([key, joint]) => {
    const node = scene.getObjectByName(joint.node);
    if (!node) throw new Error(`Model is missing ${joint.node}`);
    return {
      key,
      node,
      sign: joint.sign,
      axis: new Vector3(...joint.axis).normalize(),
      position: node.position.clone(),
      rotation: node.quaternion.clone(),
      delta: new Quaternion(),
    };
  });
  return {
    apply(
      pose: Pick<
        Snapshot["pose"],
        "axial_inches" | "horizontal_degrees" | "lateral_degrees" | "fit_inches"
      >,
    ) {
      for (const joint of joints) {
        if (joint.key === "axial" || joint.key === "fit") {
          joint.node.position
            .copy(joint.position)
            .addScaledVector(
              joint.axis,
              (joint.key === "fit" ? pose.fit_inches : pose.axial_inches) *
                0.0254 *
                joint.sign,
            );
        } else {
          const angle =
            joint.key === "horizontal"
              ? pose.horizontal_degrees
              : pose.lateral_degrees;
          joint.delta.setFromAxisAngle(
            joint.axis,
            ((angle * Math.PI) / 180) * joint.sign,
          );
          joint.node.quaternion.copy(joint.rotation).premultiply(joint.delta);
        }
      }
    },
    restore() {
      for (const joint of joints) {
        joint.node.position.copy(joint.position);
        joint.node.quaternion.copy(joint.rotation);
      }
    },
  };
}
