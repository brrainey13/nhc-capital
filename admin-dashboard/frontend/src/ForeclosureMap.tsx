import { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix default marker icons (Leaflet + bundler issue)
// @ts-ignore
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

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

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch('/api/tables/ct_foreclosures/data?limit=500', {
          credentials: 'include',
        });
        const json = await res.json();
        const withCoords = (json.data || []).filter(
          (r: Foreclosure) => r.lat != null && r.lng != null
        );
        setData(withCoords);
      } catch (err) {
        console.error('Failed to fetch foreclosure data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#aaa' }}>
        Loading map data...
      </div>
    );
  }

  const CT_CENTER: [number, number] = [41.55, -72.65];

  return (
    <div style={{ height: '100%', width: '100%', position: 'relative' }}>
      <div style={{
        position: 'absolute', top: 12, left: 60, zIndex: 1000,
        background: 'rgba(30,30,30,0.85)', padding: '6px 14px', borderRadius: 8,
        color: '#ccc', fontSize: 13,
      }}>
        🏠 {data.length} CT Foreclosures
      </div>
      <MapContainer
        center={CT_CENTER}
        zoom={9}
        style={{ height: '100%', width: '100%' }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />
        {data.map((f) => (
          <Marker key={f.id} position={[f.lat, f.lng]}>
            <Popup>
              <div style={{ minWidth: 220, fontFamily: 'system-ui', fontSize: 13 }}>
                <div style={{ fontWeight: 700, marginBottom: 6, fontSize: 14 }}>
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
                <div style={{ marginBottom: 4 }}>
                  <strong>Town:</strong> {f.town}
                </div>
                <a
                  href={`${BASE_URL}?PostingId=${f.posting_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: '#4da6ff', textDecoration: 'underline' }}
                >
                  View Full Notice →
                </a>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
