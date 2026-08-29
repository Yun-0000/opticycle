import { loadFont as loadGeistSans } from "@remotion/google-fonts/Geist";
import { loadFont as loadGeistMono } from "@remotion/google-fonts/GeistMono";

const sans = loadGeistSans("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});
const mono = loadGeistMono("normal", {
  weights: ["400", "500", "600"],
  subsets: ["latin"],
});

export const sansFont = sans.fontFamily;
export const monoFont = mono.fontFamily;

export const colors = {
  bg: "#05080f",
  bgLift: "#0c1424",
  line: "#1c2a44",
  text: "#f4f7fb",
  muted: "#9aa8bd",
  teal: "#3ee0b0",
  blue: "#7aa2ff",
  coral: "#ff6b6b",
  gold: "#f0c36a",
};
