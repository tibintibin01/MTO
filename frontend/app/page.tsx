import {LandingHome} from "./components/LandingHome";
import {LandingIllustration} from "./components/LandingIllustration";

// Keep the original SVG illustration out of the interactive JavaScript bundle.
export default function Home(){
  return <LandingHome artwork={<LandingIllustration/>}/>;
}
