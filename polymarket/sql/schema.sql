--
-- PostgreSQL database dump
--

-- Dumped from database version 15.12 (Debian 15.12-0+deb12u2)
-- Dumped by pg_dump version 15.12 (Debian 15.12-0+deb12u2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_log (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    agent_name text,
    action text,
    input jsonb,
    output jsonb,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.agent_log OWNER TO postgres;

--
-- Name: human_notes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.human_notes (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    market_id uuid,
    author text,
    note text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.human_notes OWNER TO postgres;

--
-- Name: market_snapshots; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.market_snapshots (
    id integer NOT NULL,
    market_id text NOT NULL,
    yes_price double precision,
    no_price double precision,
    volume_24h double precision,
    liquidity double precision,
    snapshot_time timestamp without time zone DEFAULT now()
);


ALTER TABLE public.market_snapshots OWNER TO postgres;

--
-- Name: market_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.market_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.market_snapshots_id_seq OWNER TO postgres;

--
-- Name: market_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.market_snapshots_id_seq OWNED BY public.market_snapshots.id;


--
-- Name: markets; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.markets (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    polymarket_id text NOT NULL,
    question text NOT NULL,
    description text,
    category text,
    end_date timestamp without time zone,
    active boolean DEFAULT true,
    yes_price double precision,
    no_price double precision,
    volume_24h double precision,
    liquidity double precision,
    last_updated timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.markets OWNER TO postgres;

--
-- Name: positions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.positions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    market_id uuid,
    side text,
    entry_price double precision,
    size double precision,
    notional_usdc double precision,
    tx_hash text,
    status text DEFAULT 'open'::text,
    opened_at timestamp without time zone DEFAULT now(),
    closed_at timestamp without time zone,
    CONSTRAINT positions_side_check CHECK ((side = ANY (ARRAY['YES'::text, 'NO'::text]))),
    CONSTRAINT positions_status_check CHECK ((status = ANY (ARRAY['open'::text, 'closed'::text, 'expired'::text])))
);


ALTER TABLE public.positions OWNER TO postgres;

--
-- Name: theses; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.theses (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    market_id uuid,
    bull_case text,
    bear_case text,
    base_rate_analysis text,
    edge_hypothesis text,
    catalysts text,
    invalidation_conditions text,
    confidence_score double precision,
    created_by text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.theses OWNER TO postgres;

--
-- Name: market_snapshots id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.market_snapshots ALTER COLUMN id SET DEFAULT nextval('public.market_snapshots_id_seq'::regclass);


--
-- Name: agent_log agent_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_log
    ADD CONSTRAINT agent_log_pkey PRIMARY KEY (id);


--
-- Name: human_notes human_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.human_notes
    ADD CONSTRAINT human_notes_pkey PRIMARY KEY (id);


--
-- Name: market_snapshots market_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.market_snapshots
    ADD CONSTRAINT market_snapshots_pkey PRIMARY KEY (id);


--
-- Name: markets markets_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.markets
    ADD CONSTRAINT markets_pkey PRIMARY KEY (id);


--
-- Name: markets markets_polymarket_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.markets
    ADD CONSTRAINT markets_polymarket_id_key UNIQUE (polymarket_id);


--
-- Name: positions positions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (id);


--
-- Name: theses theses_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.theses
    ADD CONSTRAINT theses_pkey PRIMARY KEY (id);


--
-- Name: idx_markets_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_markets_active ON public.markets USING btree (active);


--
-- Name: idx_markets_polymarket_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_markets_polymarket_id ON public.markets USING btree (polymarket_id);


--
-- Name: idx_positions_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_positions_status ON public.positions USING btree (status);


--
-- Name: idx_snapshots_market_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_snapshots_market_time ON public.market_snapshots USING btree (market_id, snapshot_time);


--
-- Name: human_notes human_notes_market_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.human_notes
    ADD CONSTRAINT human_notes_market_id_fkey FOREIGN KEY (market_id) REFERENCES public.markets(id) ON DELETE CASCADE;


--
-- Name: positions positions_market_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_market_id_fkey FOREIGN KEY (market_id) REFERENCES public.markets(id) ON DELETE CASCADE;


--
-- Name: theses theses_market_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.theses
    ADD CONSTRAINT theses_market_id_fkey FOREIGN KEY (market_id) REFERENCES public.markets(id) ON DELETE CASCADE;


--
-- Name: TABLE agent_log; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.agent_log TO clawd_user;


--
-- Name: TABLE human_notes; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.human_notes TO clawd_user;


--
-- Name: TABLE market_snapshots; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.market_snapshots TO clawd_user;


--
-- Name: SEQUENCE market_snapshots_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,USAGE ON SEQUENCE public.market_snapshots_id_seq TO clawd_user;


--
-- Name: TABLE markets; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.markets TO clawd_user;


--
-- Name: TABLE positions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.positions TO clawd_user;


--
-- Name: TABLE theses; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.theses TO clawd_user;


--
-- PostgreSQL database dump complete
--

