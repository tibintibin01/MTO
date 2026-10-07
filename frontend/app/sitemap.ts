import type {MetadataRoute} from "next";
export default function sitemap():MetadataRoute.Sitemap {
  return ["/","/help","/pay-guide"].map(path=>({url:"https://mto-portal-dipaculao.vercel.app"+path}));
}
