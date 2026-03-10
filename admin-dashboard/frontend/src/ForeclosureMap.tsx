import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

interface Foreclosure {
  id: number;
  posting_id: number;
  town: string;
  address: string;
  sale_date: string;
  check_amount: number | null;
  sale_type: string;
  property_type: string;
  lat: number;
  lng: number;
  photo_url: string | null;
}

interface ILForeclosure {
  id: number;
  source: string;
  case_number: string;
  address: string;
  city: string | null;
  county: string | null;
  zip: string | null;
  sale_date: string | null;
  sale_time: string | null;
  sale_type: string | null;
  opening_bid: number | null;
  judgment_amount: number | null;
  status: string | null;
  plaintiff: string | null;
  firm_name: string | null;
  auction_com_id: string | null;
  photo_url: string | null;
  lat: number;
  lng: number;
}

interface MultiFamilyPoint {
  town: string;
  pid: number;
  address: string;
  use_desc: string;
  unit_count: number | null;
  living_area_sqft: number | null;
  year_built: number | null;
  last_sale_price: number | null;
  last_sale_date: string | null;
  lat: number;
  lng: number;
}

const BASE_URL = 'https://sso.eservices.jud.ct.gov/foreclosures/Public/PendPostDetailPublic.aspx';

const fmt = (amount: number | null) => {
  if (!amount) return 'N/A';
  return `$${Number(amount).toLocaleString()}`;
};

const saleYear = (v: string | null) => {
  if (!v) return 'N/A';
  const m = String(v).match(/\d{4}/);
  return m ? m[0] : 'N/A';
};

export default function ForeclosureMap({ onOpenComps }: { onOpenComps?: (foreclosureId: number) => void }) {
  const [foreclosures, setForeclosures] = useState<Foreclosure[]>([]);
  const [multiFamily, setMultiFamily] = useState<MultiFamilyPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [layerMode, setLayerMode] = useState<'foreclosures' | 'multifamily' | 'both'>('foreclosures');
  const [bucket, setBucket] = useState<'all' | '2_fam' | '3_fam' | '4_fam' | '5_10' | '11_25' | '25_plus'>('all');
  const [towns, setTowns] = useState<{ town: string; parcel_count: number }[]>([]);
  const [selectedTown, setSelectedTown] = useState<string>('');
  const [soldEra, setSoldEra] = useState<'all' | 'pre2000' | '2000s' | '2010s' | '2020s'>('all');
  const [multiLoading, setMultiLoading] = useState(false);
  const [stateFilter, setStateFilter] = useState<'CT' | 'IL' | 'both'>('CT');
  const [ilForeclosures, setIlForeclosures] = useState<ILForeclosure[]>([]);
  const [ilLoading, setIlLoading] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch('/api/real-estate/foreclosures?limit=500');
        if (!res.ok) {
          setError(`API error: ${res.status} ${res.statusText}`);
          return;
        }
        const json = await res.json();
        const withCoords = (Array.isArray(json) ? json : json.rows || json.data || []).filter(
          (r: Foreclosure) => r.lat != null && r.lng != null,
        );
        setForeclosures(withCoords);
      } catch (err) {
        setError(`Fetch failed: ${err}`);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  useEffect(() => {
    if (stateFilter === 'CT') {
      setIlForeclosures([]);
      return;
    }
    setIlLoading(true);
    fetch('/api/real-estate/il-foreclosures?limit=2000')
      .then((r) => r.json())
      .then((data) => {
        const withCoords = (Array.isArray(data) ? data : []).filter(
          (r: ILForeclosure) => r.lat != null && r.lng != null,
        );
        setIlForeclosures(withCoords);
      })
      .catch(() => setIlForeclosures([]))
      .finally(() => setIlLoading(false));
  }, [stateFilter]);

  useEffect(() => {
    fetch('/api/real-estate/towns')
      .then((r) => r.json())
      .then((data) => setTowns(Array.isArray(data) ? data : []))
      .catch(() => setTowns([]));
  }, []);

  useEffect(() => {
    const loadMulti = async () => {
      if (layerMode === 'foreclosures' || !selectedTown) {
        setMultiFamily([]);
        return;
      }
      setMultiLoading(true);
      try {
        const townParam = `&town=${selectedTown}`;
        const res = await fetch(`/api/real-estate/multifamily-points?bucket=${bucket}&sold_era=${soldEra}${townParam}&limit=30000`);
        const rows = await res.json();
        setMultiFamily(Array.isArray(rows) ? rows : []);
      } catch {
        setMultiFamily([]);
      } finally {
        setMultiLoading(false);
      }
    };
    loadMulti();
  }, [layerMode, bucket, selectedTown, soldEra]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading map data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-destructive text-sm">
        {error}
      </div>
    );
  }

  const CT_CENTER: [number, number] = [41.55, -72.65];
  const IL_CENTER: [number, number] = [41.85, -87.75];
  const mapCenter = stateFilter === 'IL' ? IL_CENTER : stateFilter === 'both' ? [41.7, -80.0] as [number, number] : CT_CENTER;
  const mapZoom = stateFilter === 'both' ? 6 : 9;

  return (
    <div className="h-full w-full relative">
      <div className="absolute top-3 left-3 right-3 sm:left-[60px] sm:right-auto z-[1000] bg-card/90 backdrop-blur px-3 py-2 rounded-lg border border-border shadow-lg flex gap-2 flex-wrap items-center text-foreground text-xs font-semibold">
        <select
          value={stateFilter}
          onChange={(e) => setStateFilter(e.target.value as 'CT' | 'IL' | 'both')}
          className="bg-muted text-foreground border border-border rounded-md px-2 py-1.5 text-xs min-h-[36px] font-bold"
        >
          <option value="CT">🏠 Connecticut</option>
          <option value="IL">🏠 Illinois</option>
          <option value="both">🏠 CT + IL</option>
        </select>
        {(stateFilter === 'CT' || stateFilter === 'both') && (
          <span>CT: {foreclosures.length}</span>
        )}
        {stateFilter === 'both' && <span>•</span>}
        {(stateFilter === 'IL' || stateFilter === 'both') && (
          <span>IL: {ilLoading ? '...' : ilForeclosures.length}</span>
        )}
        {stateFilter !== 'IL' && (
          <>
            <span>•</span>
            <span>Multi-Family: {multiLoading ? '...' : multiFamily.length}</span>
          </>
        )}
        <select
          value={layerMode}
          onChange={(e) => setLayerMode(e.target.value as 'foreclosures' | 'multifamily' | 'both')}
          className="bg-muted text-foreground border border-border rounded-md px-2 py-1.5 text-xs min-h-[36px]"
        >
          <option value="foreclosures">Foreclosure Listings</option>
          <option value="multifamily">Multi-Family by Town</option>
          <option value="both">Both layers</option>
        </select>
        {layerMode !== 'foreclosures' && stateFilter !== 'IL' && (
          <>
            <select
              value={selectedTown}
              onChange={(e) => setSelectedTown(e.target.value)}
              className="bg-muted text-foreground border border-border rounded-md px-2 py-1.5 text-xs min-h-[36px] max-w-[180px] flex-1 min-w-[120px]"
            >
              <option value="" disabled>Select town...</option>
              <option value="all">All Towns</option>
              {towns.map((t) => (
                <option key={t.town} value={t.town}>
                  {t.town.replace('CT', '')} ({t.parcel_count.toLocaleString()})
                </option>
              ))}
            </select>
            <select
              value={bucket}
              onChange={(e) => setBucket(e.target.value as 'all' | '2_fam' | '3_fam' | '4_fam' | '5_10' | '11_25' | '25_plus')}
              className="bg-muted text-foreground border border-border rounded-md px-2 py-1.5 text-xs min-h-[36px]"
            >
              <option value="all">All 2+ units</option>
              <option value="2_fam">2 Family</option>
              <option value="3_fam">3 Family</option>
              <option value="4_fam">4 Family</option>
              <option value="5_10">5–10 units</option>
              <option value="11_25">11–25 units</option>
              <option value="25_plus">25+ units</option>
            </select>
            <select
              value={soldEra}
              onChange={(e) => setSoldEra(e.target.value as 'all' | 'pre2000' | '2000s' | '2010s' | '2020s')}
              className="bg-muted text-foreground border border-border rounded-md px-2 py-1.5 text-xs min-h-[36px]"
            >
              <option value="all">Any sale date</option>
              <option value="pre2000">Pre-2000</option>
              <option value="2000s">2000–2009</option>
              <option value="2010s">2010–2019</option>
              <option value="2020s">2020–Current</option>
            </select>
          </>
        )}
      </div>
      <MapContainer
        key={stateFilter}
        center={mapCenter}
        zoom={mapZoom}
        style={{ height: '100%', width: '100%', background: '#e8f4f8' }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />

        {/* CT Foreclosures (red) */}
        {(layerMode === 'foreclosures' || layerMode === 'both') && (stateFilter === 'CT' || stateFilter === 'both') && foreclosures.map((f) => (
          <CircleMarker
            key={`f-${f.id}`}
            center={[f.lat, f.lng]}
            radius={7}
            fillColor="#ff4757"
            fillOpacity={0.85}
            color="#fff"
            weight={1.5}
          >
            <Popup>
              <div style={{ minWidth: 240, fontFamily: 'system-ui', fontSize: 13, lineHeight: 1.5 }}>
                {f.photo_url && (
                  <img
                    src={`/api/real-estate/photo/${f.id}`}
                    alt={f.address}
                    style={{ width: '100%', maxHeight: 160, objectFit: 'cover', borderRadius: 6, marginBottom: 8 }}
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                )}
                <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 14, color: '#1a1a2e' }}>
                  {f.address}
                </div>
                <div style={{ marginBottom: 4 }}>
                  <strong>Sale Date:</strong> {f.sale_date || 'N/A'}
                </div>
                <div style={{ marginBottom: 4 }}>
                  <strong>Check Amount:</strong> {fmt(f.check_amount)}
                </div>
                <div style={{ marginBottom: 4 }}>
                  <strong>Type:</strong> {f.property_type || 'N/A'} — {f.sale_type || 'N/A'}
                </div>
                <div style={{ marginBottom: 6 }}>
                  <strong>Town:</strong> {f.town}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button
                    onClick={() => onOpenComps?.(f.id)}
                    style={{
                      background: '#6c5ce7', color: '#fff', border: 'none', borderRadius: 6,
                      padding: '6px 10px', cursor: 'pointer', fontWeight: 600, fontSize: 12,
                    }}
                  >
                    View Sales Comps
                  </button>
                  <a
                    href={`${BASE_URL}?PostingId=${f.posting_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: '#2e86de', fontWeight: 600, textDecoration: 'none', alignSelf: 'center' }}
                  >
                    Full Notice →
                  </a>
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* IL Foreclosures (orange) */}
        {(layerMode === 'foreclosures' || layerMode === 'both') && (stateFilter === 'IL' || stateFilter === 'both') && ilForeclosures.map((f) => (
          <CircleMarker
            key={`il-${f.id}`}
            center={[f.lat, f.lng]}
            radius={7}
            fillColor="#ffa502"
            fillOpacity={0.85}
            color="#fff"
            weight={1.5}
          >
            <Popup>
              <div style={{ minWidth: 240, fontFamily: 'system-ui', fontSize: 13, lineHeight: 1.5 }}>
                {f.photo_url && (
                  <img
                    src={f.photo_url}
                    alt={f.address}
                    style={{ width: '100%', maxHeight: 160, objectFit: 'cover', borderRadius: 6, marginBottom: 8 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                )}
                <div style={{ fontWeight: 700, marginBottom: 4, fontSize: 14, color: '#1a1a2e' }}>
                  {f.address}
                </div>
                <div style={{ marginBottom: 4, color: '#666', fontSize: 12 }}>
                  {f.city}{f.county ? ` · ${f.county} County` : ''}{f.zip ? ` · ${f.zip}` : ''}
                </div>
                {f.sale_date && (
                  <div style={{ marginBottom: 4 }}>
                    <strong>Sale Date:</strong> {f.sale_date}{f.sale_time ? ` at ${f.sale_time}` : ''}
                  </div>
                )}
                {f.opening_bid != null && (
                  <div style={{ marginBottom: 4 }}>
                    <strong>Opening Bid:</strong> {fmt(f.opening_bid)}
                  </div>
                )}
                {f.judgment_amount != null && (
                  <div style={{ marginBottom: 4 }}>
                    <strong>Judgment:</strong> {fmt(f.judgment_amount)}
                  </div>
                )}
                <div style={{ marginBottom: 4 }}>
                  <strong>Type:</strong> {f.sale_type || 'N/A'}
                  {f.status ? ` — ${f.status}` : ''}
                </div>
                {f.plaintiff && (
                  <div style={{ marginBottom: 4, fontSize: 11 }}>
                    <strong>Lender:</strong> {f.plaintiff.length > 60 ? f.plaintiff.slice(0, 60) + '…' : f.plaintiff}
                  </div>
                )}
                <div style={{ marginBottom: 4, fontSize: 11 }}>
                  <strong>Source:</strong> {f.source === 'tjsc' ? 'TJSC' : f.source === 'intercounty' ? 'Intercounty' : 'Auction.com'}
                  {f.case_number ? ` · ${f.case_number}` : ''}
                </div>
                {f.auction_com_id && (
                  <a
                    href={`https://www.auction.com/details/${f.auction_com_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: '#2e86de', fontWeight: 600, textDecoration: 'none', fontSize: 12 }}
                  >
                    View on Auction.com →
                  </a>
                )}
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {/* Multi-Family (blue, CT only) */}
        {(layerMode === 'multifamily' || layerMode === 'both') && multiFamily.map((m) => (
          <CircleMarker
            key={`m-${m.town}-${m.pid}`}
            center={[m.lat, m.lng]}
            radius={5}
            fillColor="#2e86de"
            fillOpacity={0.75}
            color="#fff"
            weight={1}
          >
            <Popup>
              <div style={{ minWidth: 220, fontFamily: 'system-ui', fontSize: 13, lineHeight: 1.5 }}>
                <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 14, color: '#1a1a2e' }}>{m.address}</div>
                <div><strong>Town:</strong> {m.town.replace('CT', '')}</div>
                <div><strong>Units:</strong> {m.unit_count ?? 'N/A'}</div>
                <div><strong>Sqft:</strong> {m.living_area_sqft?.toLocaleString() ?? 'N/A'}</div>
                <div><strong>Year Built:</strong> {m.year_built ?? 'N/A'}</div>
                <div><strong>Year Last Sold:</strong> {saleYear(m.last_sale_date)}</div>
                <div><strong>Sold Price:</strong> {fmt(m.last_sale_price)}</div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
