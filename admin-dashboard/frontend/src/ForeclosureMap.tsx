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
}

const BASE_URL = 'https://sso.eservices.jud.ct.gov/foreclosures/Public/PendPostDetailPublic.aspx';

const fmt = (amount: number | null) => {
  if (!amount) return 'N/A';
  return `$${Number(amount).toLocaleString()}`;
};

export default function ForeclosureMap() {
  const [data, setData] = useState<Foreclosure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch('/api/tables/ct_foreclosures/data?limit=500');
        if (!res.ok) {
          setError(`API error: ${res.status} ${res.statusText}`);
          return;
        }
        const json = await res.json();
        const withCoords = (json.rows || json.data || []).filter(
          (r: Foreclosure) => r.lat != null && r.lng != null
        );
        setData(withCoords);
      } catch (err) {
        setError(`Fetch failed: ${err}`);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#aaa', fontSize: 16 }}>
        Loading map data...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#ff6b6b', fontSize: 14 }}>
        {error}
      </div>
    );
  }

  const CT_CENTER: [number, number] = [41.55, -72.65];

  return (
    <div style={{ height: '100%', width: '100%', position: 'relative' }}>
      <div style={{
        position: 'absolute', top: 12, left: 60, zIndex: 1000,
        background: 'rgba(30,60,90,0.9)', padding: '8px 16px', borderRadius: 8,
        color: '#fff', fontSize: 13, fontWeight: 600,
        border: '1px solid rgba(0,0,0,0.15)', boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
      }}>
        🏠 {data.length} CT Foreclosures
      </div>
      <MapContainer
        center={CT_CENTER}
        zoom={9}
        style={{ height: '100%', width: '100%', background: '#e8f4f8' }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        {data.map((f) => (
          <CircleMarker
            key={f.id}
            center={[f.lat, f.lng]}
            radius={7}
            fillColor="#ff4757"
            fillOpacity={0.85}
            color="#fff"
            weight={1.5}
          >
            <Popup>
              <div style={{ minWidth: 240, fontFamily: 'system-ui', fontSize: 13, lineHeight: 1.5 }}>
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
                <a
                  href={`${BASE_URL}?PostingId=${f.posting_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: '#2e86de', fontWeight: 600, textDecoration: 'none' }}
                >
                  View Full Notice →
                </a>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
