import {loadFont} from "@remotion/google-fonts/SpaceMono";

const {fontFamily} = loadFont("normal", {weights: ["400", "700"], subsets: ["latin"]});

export const typeface = fontFamily;

export const c = {
  black: "#000000",
  white: "#F7F7F2",
  gray: "#909090",
  dim: "#4B4B4B",
  acid: "#A6FF00",
  red: "#FF2638",
  yellow: "#FCFF76",
  orange: "#FF5B29",
  paper: "#F0EEE6",
  ink: "#080808"
} as const;
