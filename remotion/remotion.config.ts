/**
 * Remotion CLI config for the Opticycle demo.
 * Scene motion uses useCurrentFrame() and interpolate(), not CSS animation.
 */

import { Config } from "@remotion/cli/config";
import { enableTailwind } from "@remotion/tailwind-v4";

Config.setRspack(true);
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setBrowserExecutable("/usr/bin/google-chrome");
Config.overrideBundlerConfig(enableTailwind);
