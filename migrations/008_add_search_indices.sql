-- Migration: Add Search Indices for Live Search Performance
-- Version: 008

-- Index for Owner Name to speed up live search and reporting
CREATE INDEX idx_properties_owner_name ON properties(owner_name);

-- Index for payor_name to support quick lookups in ledger
CREATE INDEX idx_properties_payor_name ON properties(payor_name);

-- Index for location to support address-based live search
CREATE INDEX idx_properties_location ON properties(location);
