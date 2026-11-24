static const char* kHlsl = R"HLSL(
Texture2D bg : register(t0);
Texture2D edgeTex : register(t3);   // qirra uchun alohida Gauss sigma
Texture2D blurTex : register(t2);   // Gauss xiralashtirilgan orqa fon (frost): faqat popup uchun
Texture2D content : register(t1);   // oyna kontenti (premultiplied BGRA): shisha USTIDA bir xil oynada chiziladi (qo'shimcha oyna bilan sinxron muammosi yo'q)
SamplerState smp : register(s0);
SamplerState smpMip : register(s1);   // to'g'ri mip zanjiri (MaxLOD cheksiz): orqa fon yorqinligi uchun
cbuffer G : register(b0) {
    float2 res;    float2 pad;
    float2 light;  float dpr;  float count;
    float ior;     float thick; float bevel; float disp;
    float blur;    float spec;  float absorb; float merge;
    float shadowK; float shadowOff; float extraLod; float debugComposite;
    float hasContent; float rimOnly; float frost; float edge;
    float2 winOff; float2 look;
    float4 look2;   // x = markaziy linza (chetdagi sinish markazga silliq so'nadi), y = yuqoridan yorug'lik qaytishi kuchi (1 = eski)   // look.x = Fresnel kuchi (1 = eski), look.y = chet yorug'ligi (1 = eski)   // qo'zg'almas katta oyna: shisha chizilgan to'rtburchakning oyna ichidagi boshi
};
cbuffer S : register(b1) { float4 S[256 * 3]; }
cbuffer BC : register(b3) { float4 bdir; }   // xiralashtirish: xy = qadam yo'nalishi, z = sigma (piksel)
cbuffer M : register(b2) { float4 mDesk; float4 mHist[4]; }   // mDesk: xy = monitor boshi (ekran pikseli), z = tarix soni
struct VO { float4 pos : SV_Position; };
VO vs(uint id : SV_VertexID) {
    VO o; float2 uv = float2((id << 1) & 2, id & 2);
    o.pos = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1); return o;
}
float sst(float a, float b, float x) { float t = saturate((x - a) / (b - a)); return t * t * (3.0 - 2.0 * t); }
float sdRR(float2 p, float2 b, float r) { float2 q = abs(p) - b + r; return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r; }
float smin_(float a, float b, float k) { float h = max(k - abs(a - b), 0.0) / k; return min(a, b) - h * h * k * 0.25; }

static float gMin = 1e5;
static float4 gTint = 0;
static float2 gMat = 1;
static float2 gCtr = 0, gHalfSz = 1;   // eng yaqin shaklning markazi va yarim o'lchami (markaziy linza uchun)
float sdAllR(float2 p, float softR) {   // softR > 0: burchak radiusi kamida softR (silliq chuqurlik/gradient uchun)
    float d = 1e5, bm = 1e5; float4 bt = 0; float2 bmat = 1; float2 bctr = 0, bhalf = 1;
    float mk = max(merge, 0.5);
    int n = (int)count;
    [loop] for (int k = 0; k < n; k++) {
        float4 r = S[k * 3 + 0];
        float4 m = S[k * 3 + 1];
        float bd = length(max(abs(p - r.xy) - r.zw, 0.0));
        if (bd > max(d, 0.0) + mk) continue;   // ichma-ich shakl (katta shakl ichida): d manfiy bo'lganda ham o'tkazib yuborilmaydi
        float bi = min(r.z, r.w);
        float di = sdRR(p - r.xy, r.zw, min(max(m.x, softR), bi));
        bool nested = d < 0.0 && di < 0.0;
        bool take = nested ? bi < bm : di < d;
        if (take) { bm = bi; bt = S[k * 3 + 2]; bmat = m.yz; bctr = r.xy; bhalf = r.zw; }
        // Ichma-ich shakl (kichigi katta shaklning ichida): u katta shakl USTIDA turadi, ya'ni uning o'z qirrasi va chuqurligi ishlaydi
        // (birlashma d = min(...) bo'lsa kichik shaklning chegarasi hech qachon ko'rinmaydi). Faqat sezilarli kichik shakllar uchun (suyuq birlashma buzilmasin).
        d = (nested && take && bi < 0.7 * bm) ? di : smin_(d, di, mk);
    }
    gMin = bm; gTint = bt; gMat = bmat; gCtr = bctr; gHalfSz = bhalf;
    return d;
}
float sdAll(float2 p) { return sdAllR(p, 0.0); }
float3 bgAt(float2 px, float lod) {
    float2 sz; bg.GetDimensions(sz.x, sz.y);
    return bg.SampleLevel(smp, clamp((px + pad) / sz, 0.001, 0.999), lod).rgb;
}
// Siqilish darajasiga moslangan filtrlash: namuna koordinatasining ekran hosilalari bo'yicha mip va anizotropiya tanlanadi
// (linza qirrasida tasvir kuchli siqiladi: qat'iy xiralik bilan namuna olish aliasing/"mikro-glitch" beradi). fs = qo'shimcha xiralik (2^lod).
float3 bgG(float2 p, float2 dx, float2 dy) {
    float2 sz; bg.GetDimensions(sz.x, sz.y);
    return bg.SampleGrad(smp, clamp((p + pad) / sz, 0.001, 0.999), dx / sz, dy / sz).rgb;
}
float2 refractOffset(float ior_, float3 Nn, float t, float dist, out float tir) {
    float3 R = refract(float3(0, 0, -1), Nn, 1.0 / ior_);
    float2 inner = R.xy / sqrt(R.z * R.z + 0.01) * t;            // max(-R.z, 0.08) o'rniga: burilish nuqtasiz, uzluksiz
    float sRaw = ior_ * length(R.xy);
    float s = 0.985 * tanh(sRaw / 0.985);                        // to'liq ichki qaytish chegarasida qattiq kesish o'rniga silliq to'yinish
    tir = smoothstep(0.90, 0.985, sRaw);
    float3 O = float3(R.xy * ior_ * (s / max(sRaw, 1e-5)), -sqrt(max(1.0 - s * s, 1e-4)));
    float2 outer = O.xy / (-O.z) * dist;
    return inner + outer;
}
float4 ps(VO i) : SV_Target {
    float2 px = i.pos.xy - winOff;
    float3 col = bgAt(px, 0.0);
    float2 bsz; bg.GetDimensions(bsz.x, bsz.y);
    float lum = saturate(dot(bg.SampleLevel(smpMip, clamp((px + pad) / bsz, 0.001, 0.999), 6.0).rgb, float3(0.299, 0.587, 0.114)));   // silliq o'rtacha yorqinlik (mip 6)
    float d = sdAll(px);
    float halfMin = gMin; float4 tint = gTint; float2 gm = gMat;
    bool clearIn = gm.x < 0.0;
    gm.x = abs(gm.x);
    float shA = 0.0, glassM = 0.0; float3 glassC = 0;
    float3 base = col;

    if (d > 0.0 && d < (90.0 + shadowOff * 2.0) * dpr) {
        float ds = sdAll(px - float2(0.0, shadowOff * dpr));
        float sh = exp(-max(ds, 0.0) / ((10.0 + shadowOff * 0.5) * dpr)) * shadowK * lerp(1.0, 0.25, lum);
        shA = sh;
    }
    if (d < 1.5 * dpr + 6.0) {   // keng chegara: ddx/ddy chet piksellarida noaniq bo'lmasligi uchun (u yerda m = 0)
        float zR = min(bevel * gm.x * dpr, halfMin * 0.5);
        float depth = max(-d, 0.0);
        float e = 1.0;
        // Sinish profili YUMSHOQ shakldan (burchak radiusi >= zR): aks holda zona burchak radiusidan keng bo'lsa diagonalda gradient keskin almashib chok chiqadi
        float depthS = max(-sdAllR(px, zR), 0.0);
        float2 g = float2(sdAllR(px + float2(e, 0.0), zR) - sdAllR(px - float2(e, 0.0), zR),
                          sdAllR(px + float2(0.0, e), zR) - sdAllR(px - float2(0.0, e), zR));
        g = normalize(g + 1e-6);
        float dd = clamp(max(depthS, min(depth, 0.25 * zR)), 0.0, zR);   // burchak uchi (yumshoq shakldan tashqarida): haqiqiy chuqurlikning kichik qismi, eng kuchli sinish emas
        // Konveks "skvirkl" profil h = zR (1 - x^4)^(1/4), x = 1 - dd/zR: markazda tekislikka egrilik bilan uzluksiz o'tadi (doira profili o'tishda sinadi)
        float xq = 1.0 - dd / max(zR, 1.0);
        float x4 = xq * xq * xq * xq;
        float h = zR * pow(max(1.0 - x4, 0.0), 0.25);
        float dh = min(xq * xq * xq * pow(max(1.0 - x4, 1e-4), -0.75), 6.0);
        float2 uC = clamp((px - gCtr) / max(gHalfSz, 1.0), -1.0, 1.0);   // shakl markazidan chiqish: -1..1 (burilishsiz, diagonalda ham uzluksiz)
        float3 Ne = normalize(float3(g * dh, 1.0));   // faqat chetning o'zi: aks, Fresnel va yaltirash shundan (linza ularni siljitmasin)
        float3 Nn = normalize(float3(g * dh + uC * look2.x, 1.0));   // yostiq shaklidagi yengil linza: markazda 0, chetga qarab o'sib, chetdagi sinishga silliq ulanadi
        float th = thick * abs(gm.y);
        float t = (0.25 * zR + h) * th / max(zR, 1.0) * dpr;
        float dist = 0.5 * th * dpr;
        float tirR, tirG, tirB;
        float2 oR = refractOffset(ior - disp, Nn, t, dist, tirR);
        float2 oG = refractOffset(ior,        Nn, t, dist, tirG);
        float2 oB = refractOffset(ior + disp, Nn, t, dist, tirB);
        float hz = h / max(zR, 1.0);
        float lod = clearIn ? extraLod * 0.3 + (1.0 - hz) * blur * 0.9 : blur + extraLod + hz * blur * 0.6;
        float k = (0.6 + lod) * dpr;
        float2 pr = px + oR, pg = px + oG, pb = px + oB;
        float fs = exp2(lod);
        float2 rdx = ddx(pr) * fs, rdy = ddy(pr) * fs, gdx = ddx(pg) * fs, gdy = ddy(pg) * fs, bdx = ddx(pb) * fs, bdy = ddy(pb) * fs;
        float3 tr = float3(
            (bgG(pr, rdx, rdy).r * 2.0 + bgG(pr + float2(k, 0), rdx, rdy).r + bgG(pr - float2(k, 0), rdx, rdy).r + bgG(pr + float2(0, k), rdx, rdy).r + bgG(pr - float2(0, k), rdx, rdy).r) / 6.0,
            (bgG(pg, gdx, gdy).g * 2.0 + bgG(pg + float2(k, 0), gdx, gdy).g + bgG(pg - float2(k, 0), gdx, gdy).g + bgG(pg + float2(0, k), gdx, gdy).g + bgG(pg - float2(0, k), gdx, gdy).g) / 6.0,
            (bgG(pb, bdx, bdy).b * 2.0 + bgG(pb + float2(k, 0), bdx, bdy).b + bgG(pb - float2(k, 0), bdx, bdy).b + bgG(pb + float2(0, k), bdx, bdy).b + bgG(pb - float2(0, k), bdx, bdy).b) / 6.0);
        if (edge > 0.5) {   // qirra xiraligi: refraksiya qilingan joydan olingan Gauss nusxa, qirrada to'liq, ichkariga so'nadi
            float2 esz; edgeTex.GetDimensions(esz.x, esz.y);
            float3 eb = edgeTex.SampleLevel(smp, clamp((px + oG + pad) / esz, 0.001, 0.999), 0).rgb;
            tr = lerp(tr, eb, 1.0 - sst(0.0, zR * 1.1, depth));
        }
        bool frostOn = frost > 0.5;   // kontent hali yuklanmagan bo'lsa ham ichki qism shaffof qolmaydi (aks holda haqiqiy keskin ish stoli chiziqlari ko'rinadi)   // frost markazi faqat shisha Qt oynasi OSTIDA bo'lganda (kontent shisha oynasida chiziladi)
        if (frost > 0.5) {   // frost: ichki qism haqiqiy Gauss xiraligi (mip bloklari emas), qirrada tiniq sinish saqlanadi
            float2 fsz; blurTex.GetDimensions(fsz.x, fsz.y);
            float3 fb = blurTex.SampleLevel(smp, clamp((px + oG + pad) / fsz, 0.001, 0.999), 0).rgb;
            tr = lerp(tr, fb, sst(0.0, zR * 1.1, depth));
        }
        if (debugComposite > 1.5 && debugComposite < 2.5) return float4(tr, 1);
        if (debugComposite > 2.5 && debugComposite < 3.5) return float4(lum, lum, lum, 1);
        if (debugComposite > 3.5 && debugComposite < 4.5) return float4(depth / 100.0, zR / 100.0, frost * 0.5, 1);
        if (debugComposite > 4.5 && debugComposite < 5.5) return float4(tint.rgb, 1);
        if (debugComposite > 5.5 && debugComposite < 6.5) return float4(tint.a, gm.x * 0.5 + 0.5, gm.y, 1);
        float path = t / max(abs(refract(float3(0, 0, -1), Nn, 1.0 / ior).z), 0.1) / dpr;
        tr *= exp(-absorb * path * float3(0.0042, 0.0036, 0.0030) * (1.0 - 0.7 * lum));
        tr = lerp(tr, tr * float3(0.98, 0.99, 1.02), 0.6);
        tr *= lerp(1.0, 0.93, lum);
        if (tint.a < 0.0) {
            // Xameleon rejimi (tint.a manfiy; |a| = kuch): shisha rangi fon yorqinligiga moslashadi (qorong'i fonda ochroq, yorug' fonda to'qroq)
            // va fon rangidan biroz oladi, xuddi matn kabi
            float3 lightT = lerp(tint.rgb, float3(1.0, 1.0, 1.0), 0.5);
            float3 darkT = tint.rgb * 0.78;
            float3 tc = lerp(lightT, darkT, smoothstep(0.28, 0.62, lum));
            tc = lerp(tc, tr, 0.18);
            tr = lerp(tr, tc, -tint.a);
        } else {
            tr = lerp(tr, tint.rgb * (0.5 + 0.5 * dot(tr, float3(0.3333, 0.3333, 0.3333))), tint.a);
        }
        float cosT = clamp(Ne.z, 0.0, 1.0);
        float fres = max(look.x, 0.01);
        float F = 0.04 + 0.96 * pow(1.0 - cosT, max(5.0 - 2.5 * (fres - 1.0), 1.6));   // fres oshsa Fresnel kengayadi va kuchayadi
        float topK = look2.y;
        float3 env = lerp(float3(0.04, 0.04, 0.04), float3(0.82, 0.82, 0.82) * topK, clamp(Ne.y * -0.5 + 0.5, 0.0, 1.0));   // yuqoridan kelgan yorug'lik topK bilan boshqariladi, pastki qorong'i qism o'zgarmaydi
        env += float3(0, 0, 0) * clamp(Ne.x * 0.5 + 0.5, 0.0, 1.0);
        float3 refl = env * F * 0.35 * fres * lerp(1.0, 0.4, lum);
        float tirv = max(max(tirR, tirG), tirB);
        float3 tirGlow = float3(0.9, 0.9, 0.9) * pow(1.0 - cosT, 3.0) * 0.12 * fres * (0.4 + 0.6 * tirv) * lerp(1.0, 0.35, lum);
        float3 V = float3(0, 0, 1);
        float3 L1 = normalize(float3(-0.55 + light.x * 0.5, -0.65 + light.y * 0.5, 0.75));
        float3 L2 = normalize(float3(0.60 - light.x * 0.3, 0.55 - light.y * 0.3, 0.55));
        float s1 = pow(max(dot(Ne, normalize(L1 + V)), 0.0), 160.0) * topK;
        float s2 = pow(max(dot(Ne, normalize(L2 + V)), 0.0), 110.0) * 0.5;
        float cornerK = 1.0 - sst(0.08, 0.40, abs(g.x * g.y) * 2.0);   // burchakda (g diagonal) nuqtaviy yaltirash so'nadi
        float3 specc = (s1 + s2) * spec * 1.3 * max(look.y, 0.0) * cornerK;
        float3 glass = tr * (1.0 - F * 0.9) + refl + tirGlow + specc;
        if (any(isnan(glass)) || any(isinf(glass))) glass = col;
        glass = clamp(glass, 0.0, 1.0);
        float edge = sst(2.0 * dpr, 0.0, depth) * sst(-1.5 * dpr, 0.0, -d);
        float topBias = clamp(dot(g, float2(-0.6, -0.8)) * 0.5 + 0.5, 0.0, 1.0);
        glass += max(1.0 - 1.6 * lum, -0.28) * edge * (0.2 + 0.6 * topBias * topK) * 0.10 * max(look.y, 0.0);
        glass = clamp(glass, 0.0, 1.0);
        // Luminance ceiling keeps white foreground readable on bright backdrops.
        float adaptedLuma = dot(pow(max(glass, 0), 2.2), float3(.2126,.7152,.0722));
        if (look2.z > .5) glass *= min(1.0, pow(.12 / max(adaptedLuma, .0001), 1.0/2.2));
        float m = 1.0 - sst(-0.8 * dpr, 1.2 * dpr, d);
        // "Ramka" (thick<0) va, rimOnly rejimida, "tiniq ichki" shisha: markaz TO'LIQ shaffof (tagidagi hamma narsa DWM orqali jonli), faqat sinadigan qirra chiziladi
        float ringA = (gm.y < 0.0 || (clearIn && rimOnly > 0.5)) ? 1.0 - sst(zR * 0.55, zR * 1.2, depth) : 1.0;
        if (frostOn) ringA = 1.0;   // xira markaz: butun shisha yuzasi orqa fonning Gauss nusxasi
        m *= ringA;
        glassC = glass; glassM = m;
    }
    float a = glassM + shA * (1.0 - glassM);
    float4 outc = float4(glassC * glassM, a);
    if (hasContent > 0.5) {   // kontent shisha ustida: premultiplied "over"
        float4 c = content.Load(int3((int2)px, 0));
        // Moslashuvchan matn rangi: orqa fon qorong'i bo'lsa kulrang/qora (kam to'yingan) kontent ochga aylanadi; rangli ikonkalar o'zgarmaydi
        float3 u = c.rgb / max(c.a, 1e-4);
        float sat = max(u.r, max(u.g, u.b)) - min(u.r, min(u.g, u.b));
        float k = sst(0.62, 0.38, lum) * (1.0 - sst(0.12, 0.30, sat));
        if (hasContent > 2.5) {
            // Yumshoq xameleon (terminal): rangli piksellar o'z rangini saqlaydi, fon yorqinligiga faqat sal moslashadi (oqqa 20%, yorug' fonda 18% qorayadi)
            float satK = sst(0.20, 0.40, sat);
            float adapt = sst(0.28, 0.62, lum);
            float3 tcol = lerp(lerp(u, float3(1.0, 1.0, 1.0), 0.20), u * 0.82, adapt);
            u = lerp(lerp(u, 1.0 - u, k), tcol, satK);
            c.rgb = u * c.a;
        } else if (hasContent > 1.5) {
            // Xameleon kontent (haqiqiy emoji): rangli (to'yingan) PIKSELLAR fon yorqinligiga moslashadi va fon rangidan biroz oladi; to'q belgilar (ko'z, og'iz) o'zgarmaydi: kontrast saqlanadi
            float satK = sst(0.20, 0.40, sat);
            float Yc = dot(u, float3(0.299, 0.587, 0.114));
            float bright = sst(0.30, 0.55, Yc);
            float adapt = sst(0.28, 0.62, lum);                       // 0 = qorong'i fon, 1 = yorug' fon
            // Qorong'i fonda ranglar RAQAMLAR kremiga (0.95,0.91,0.84) yaqinlashadi (jonli, ochiq), yorug' fonda raqamlar to'q-ko'kiga (0.06,0.09,0.16)
            float3 lightT = lerp(u, float3(0.95, 0.91, 0.84), 0.50) * 1.06;
            float3 darkT = lerp(u, float3(0.06, 0.09, 0.16), 0.14);
            float3 tcol = lerp(lightT, darkT, adapt);
            tcol = lerp(tcol, bgAt(px, 4.0), 0.04);
            float3 uInv = lerp(u, 1.0 - u, k);   // kam to'yingan piksellar (matn) avvalgidek inversiya qilinadi
            u = lerp(uInv, tcol, satK * bright);
            c.rgb = u * c.a;
        } else {
            c.rgb = lerp(u, 1.0 - u, k) * c.a;
        }
        outc = float4(c.rgb + (1.0 - c.a) * outc.rgb, c.a + (1.0 - c.a) * outc.a);
    }
    if (debugComposite > 0.5) outc = float4(outc.rgb + (1.0 - outc.a) * base, 1.0);
    return outc;
}

)HLSL" R"HLSL(
// Orqa fon nusxasini (monitor kadri) yangilashda shisha qirrasi egallagan joylar eski qiymatida qoladi: aks holda DDA kadrida shishaning
// o'zi ko'rinib, u o'z-o'zini sindirib qayta aloqa bo'lardi. mHist: oynaning oxirgi o'rinlari (kadr kechikishi uchun). Maska tashqarisi chizilmaydi (discard).
float4 psMask(VO i) : SV_Target {
    float2 sp = i.pos.xy + mDesk.xy;
    bool m = false;
    [loop] for (int k = 0; k < 4; k++) {
        if ((float)k >= mDesk.z) break;
        float d = sdAll(sp - mHist[k].xy);
        float2 gm = gMat;
        bool rim = gm.y < 0.0 || gm.x < 0.0;
        float zR = min(bevel * abs(gm.x) * dpr, gMin * 0.5);
        float lim = (rim && mDesk.w < 0.5) ? zR * 1.3 + 5.0 * dpr : 1e5;   // mDesk.w = 1: oyna ichki qismi ham muzlatiladi (popup: shaffof Qt oynasi kadrda qora chiqadi)
        if (d < 6.0 * dpr && d > -lim) m = true;
    }
    if (!m) discard;
    return bg.Load(int3((int2)i.pos.xy, 0));
}

// Ikki o'tishli Gauss xiralashtirish (gorizontal, keyin vertikal): popup orqa fonining muzlatilgan nusxasi uchun, o'zgarganda bir marta
// Boshqa shisha oynaning (alfali) tasviri orqa fonga "over" aralashtiriladi: bdir.xy = qatlam teksturasidagi boshi
float4 psBlit(VO i) : SV_Target { int2 p = int2(i.pos.xy) + int2((int)bdir.x, (int)bdir.y); return bg.Load(int3(p, 0)); }

float4 psBlur(VO i) : SV_Target {
    float2 sz; bg.GetDimensions(sz.x, sz.y);
    float2 uv = i.pos.xy / sz;
    float sigma = max(bdir.z, 0.5);
    int R = (int)ceil(sigma * 3.0);
    float3 acc = 0; float ws = 0;
    [loop] for (int k = -R; k <= R; k++) {
        float w = exp(-0.5 * (float)(k * k) / (sigma * sigma));
        acc += w * bg.SampleLevel(smp, clamp(uv + bdir.xy * (float)k / sz, 0.0005, 0.9995), 0).rgb;
        ws += w;
    }
    return float4(acc / ws, 1.0);
}
)HLSL";