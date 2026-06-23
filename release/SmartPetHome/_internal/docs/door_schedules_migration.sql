-- door_schedules_migration.sql
-- Run this once in your Supabase SQL Editor (Database > SQL Editor).
--
-- Creates the door_schedules table used by scheduler.py and door.py.
-- One row per automatic_access_door device.
-- The backend reads this table every 30 s and sends open_door / close_door
-- MQTT commands at the configured times.

CREATE TABLE IF NOT EXISTS door_schedules (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id  uuid        NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  owner_id   uuid        NOT NULL,
  open_time  time,
  close_time time,
  enabled    boolean     NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Row Level Security (same pattern as other user-owned tables)
ALTER TABLE door_schedules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own door schedules"
  ON door_schedules
  FOR ALL
  USING  (owner_id = auth.uid())
  WITH CHECK (owner_id = auth.uid());
