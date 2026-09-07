package service

import (
	"path/filepath"
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/xray"
)

// A client kept across an inbound edit takes updateClientTraffics' update branch,
// which only ever ran an UPDATE: once its client_traffics row went missing the row
// could never come back, so the panel showed the client stuck at 0 B forever.
func TestUpdateClientTraffics_RecreatesMissingStatsRow(t *testing.T) {
	dbDir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dbDir)
	if err := database.InitDB(filepath.Join(dbDir, "x-ui.db")); err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	t.Cleanup(func() { _ = database.CloseDB() })

	db := database.GetDB()

	const email = "Proxy_TG"
	settings := `{"clients":[{"email":"` + email + `","secret":"ee00","enable":true,"totalGB":0,"expiryTime":0}]}`
	inbound := &model.Inbound{
		UserId:   1,
		Tag:      "in-4443-tcp",
		Enable:   true,
		Port:     4443,
		Protocol: model.MTProto,
		Settings: settings,
	}
	if err := db.Create(inbound).Error; err != nil {
		t.Fatalf("create inbound: %v", err)
	}

	// No client_traffics row exists: the client is present in both the old and the
	// new settings, so only the update branch runs.
	svc := InboundService{}
	if err := svc.updateClientTraffics(db, inbound, inbound); err != nil {
		t.Fatalf("updateClientTraffics: %v", err)
	}

	var got xray.ClientTraffic
	if err := db.Where("email = ?", email).First(&got).Error; err != nil {
		t.Fatalf("stats row for %q missing after inbound update: %v", email, err)
	}
	if got.InboundId != inbound.Id {
		t.Fatalf("InboundId = %d, want %d", got.InboundId, inbound.Id)
	}
	if !got.Enable {
		t.Fatalf("Enable = false, want true")
	}
}

// The update branch must keep updating in place when the row is there: recreating
// it would reset up/down and silently wipe the client's accumulated traffic.
func TestUpdateClientTraffics_KeepsExistingCounters(t *testing.T) {
	dbDir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dbDir)
	if err := database.InitDB(filepath.Join(dbDir, "x-ui.db")); err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	t.Cleanup(func() { _ = database.CloseDB() })

	db := database.GetDB()

	const email = "keeper"
	settings := `{"clients":[{"email":"` + email + `","secret":"ee11","enable":true,"totalGB":0,"expiryTime":0}]}`
	inbound := &model.Inbound{
		UserId:   1,
		Tag:      "in-8443-tcp",
		Enable:   true,
		Port:     8443,
		Protocol: model.MTProto,
		Settings: settings,
	}
	if err := db.Create(inbound).Error; err != nil {
		t.Fatalf("create inbound: %v", err)
	}
	if err := db.Create(&xray.ClientTraffic{
		InboundId: inbound.Id,
		Email:     email,
		Enable:    true,
		Up:        111,
		Down:      222,
	}).Error; err != nil {
		t.Fatalf("create client_traffics: %v", err)
	}

	svc := InboundService{}
	if err := svc.updateClientTraffics(db, inbound, inbound); err != nil {
		t.Fatalf("updateClientTraffics: %v", err)
	}

	var got xray.ClientTraffic
	if err := db.Where("email = ?", email).First(&got).Error; err != nil {
		t.Fatalf("stats row for %q missing: %v", email, err)
	}
	if got.Up != 111 || got.Down != 222 {
		t.Fatalf("counters = up %d / down %d, want 111 / 222", got.Up, got.Down)
	}
}
