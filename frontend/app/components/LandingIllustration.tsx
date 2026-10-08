import {FileText,Layers3,MapPin} from "lucide-react";

/** Decorative, original SVG/CSS artwork. No canvas, animation loop or requests. */
export function LandingIllustration(){
  return <div className="landing-art" aria-hidden="true">
    <div className="landing-art-orbit landing-art-orbit-one"/>
    <div className="landing-art-orbit landing-art-orbit-two"/>
    <div className="landing-art-document">
      <div className="landing-art-document-top"><span className="landing-art-document-icon"><FileText size={19}/></span><span>PROPERTY OVERVIEW</span><span className="landing-art-document-dot"/></div>
      <div className="landing-art-document-title">A clearer view.</div>
      <div className="landing-art-document-row"><span>Assessment</span><span className="landing-art-line"/></div>
      <div className="landing-art-document-row"><span>Payment history</span><span className="landing-art-line short"/></div>
      <div className="landing-art-document-row"><span>Published balance</span><span className="landing-art-line"/></div>
    </div>
    <svg className="landing-art-scene" viewBox="0 0 520 390" fill="none">
      <defs>
        <linearGradient id="parcel-surface" x1="95" y1="120" x2="410" y2="350" gradientUnits="userSpaceOnUse"><stop stopColor="#c5e9dc"/><stop offset="1" stopColor="#79bdb8"/></linearGradient>
        <linearGradient id="parcel-edge" x1="88" y1="270" x2="430" y2="300" gradientUnits="userSpaceOnUse"><stop stopColor="#174b59"/><stop offset="1" stopColor="#102e49"/></linearGradient>
        <linearGradient id="parcel-roof" x1="192" y1="100" x2="318" y2="150" gradientUnits="userSpaceOnUse"><stop stopColor="#f8d88b"/><stop offset="1" stopColor="#dca75b"/></linearGradient>
        <linearGradient id="parcel-side" x1="276" y1="173" x2="332" y2="244" gradientUnits="userSpaceOnUse"><stop stopColor="#e3edeb"/><stop offset="1" stopColor="#a9c5c5"/></linearGradient>
      </defs>
      <ellipse cx="264" cy="326" rx="193" ry="40" fill="#041325" opacity=".35"/>
      <path d="M65 230L259 124L460 235V257L265 366L65 253V230Z" fill="url(#parcel-edge)"/>
      <path d="M65 230L259 124L460 235L265 345L65 230Z" fill="url(#parcel-surface)" stroke="#d9f0e9" strokeWidth="2"/>
      <path d="M65 240L265 355L460 246" stroke="#5d9a9f" strokeOpacity=".45"/>
      <path d="M154 183L354 295M166 287L358 180" stroke="#f4faf4" strokeWidth="18"/>
      <path d="M154 183L354 295M166 287L358 180" stroke="#91bab6" strokeWidth="1" strokeDasharray="5 5"/>
      <path d="M84 232L141 202L213 243L159 274L84 232Z" fill="#5da58f" stroke="#e0f0dd"/>
      <path d="M308 243L367 211L440 252L381 285L308 243Z" fill="#63a594" stroke="#def4e6"/>
      <path d="M192 295L259 258L328 298L266 332L192 295Z" fill="#7fba9a" stroke="#d6edd8"/>
      <path d="M205 160L258 131L333 173L279 202L205 160Z" fill="#a5cda8" stroke="#ebf7df"/>
      <path d="M215 214L267 185L335 223L282 253L215 214Z" fill="#417f83" opacity=".3"/>
      <path d="M217 150L276 117L332 149V212L275 245L217 211V150Z" fill="#f5f5e9"/>
      <path d="M275 182L332 149V212L275 245V182Z" fill="url(#parcel-side)"/>
      <path d="M198 151L258 99L348 151L279 190L198 151Z" fill="url(#parcel-roof)"/>
      <path d="M258 99L258 125L279 190L348 151L258 99Z" fill="#c89147"/>
      <path d="M198 151L279 190V197L198 159V151Z" fill="#c8944f"/>
      <path d="M279 190L348 151V158L279 197V190Z" fill="#a47036"/>
      <path d="M238 185L254 194V229L238 220V185Z" fill="#154e61"/>
      <path d="M223 173L232 178V193L223 188V173ZM262 196L270 200V215L262 211V196Z" fill="#70a6ab"/>
      <path d="M287 190L300 183V200L287 207V190ZM309 177L321 170V187L309 194V177Z" fill="#5c929d"/>
      <path d="M283 208L300 198M309 194L321 187" stroke="#d9ebe7"/>
      <path d="M103 222L136 204L169 223V253L136 271L103 252V222Z" fill="#eff3e9"/>
      <path d="M136 242L169 223V253L136 271V242Z" fill="#b4cbc5"/>
      <path d="M95 222L129 189L177 223L138 246L95 222Z" fill="#235b78"/>
      <path d="M129 189L138 246L177 223L129 189Z" fill="#143d60"/>
      <path d="M115 238L128 245V265L115 257V238ZM144 243L156 236V249L144 256V243Z" fill="#6497a5"/>
      <path d="M348 232L378 215L408 232V255L378 272L348 255V232Z" fill="#f3f2df"/>
      <path d="M378 249L408 232V255L378 272V249Z" fill="#c6d4c5"/>
      <path d="M340 232L372 203L416 233L381 253L340 232Z" fill="#d89d64"/>
      <path d="M372 203L381 253L416 233L372 203Z" fill="#b7804c"/>
      <path d="M359 245L369 251V267L359 261V245ZM385 249L397 242V255L385 262V249Z" fill="#64979a"/>
      <path d="M245 283V307M316 164V187M103 193V216M400 265V289" stroke="#4e7771" strokeWidth="4" strokeLinecap="round"/>
      <ellipse cx="245" cy="280" rx="12" ry="15" fill="#347f68"/><ellipse cx="316" cy="162" rx="13" ry="18" fill="#3e896c"/>
      <ellipse cx="103" cy="190" rx="12" ry="15" fill="#428d6e"/><ellipse cx="400" cy="264" rx="13" ry="16" fill="#338369"/>
      <path d="M231 280C236 274 240 271 248 269M302 161C309 157 313 150 319 148" stroke="#72ab83" strokeWidth="2" strokeLinecap="round"/>
      <path d="M71 298L156 346M375 147L448 187" stroke="#6a9daf" strokeOpacity=".35" strokeDasharray="4 6"/>
      <circle cx="71" cy="298" r="3" fill="#89c5c5"/><circle cx="448" cy="187" r="3" fill="#d7b678"/>
    </svg>
    <div className="landing-art-pin"><MapPin size={20}/><span>Dipaculao, Aurora</span></div>
    <div className="landing-art-layer"><Layers3 size={19}/><span>Your record.<br/><strong>One clear view.</strong></span></div>
    <span className="landing-art-caption">CONNECTED TO YOUR COMMUNITY</span>
  </div>;
}
