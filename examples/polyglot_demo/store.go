// Demo fixture: a small Go service with intentional issues.
package demo

import (
	"crypto/md5"
	"database/sql"
	"fmt"
)

// Store wraps a database handle.
type Store struct {
	db *sql.DB
}

// FindUser looks up a user by name.
// Intentional finding: GO-SQL-CONCAT (CWE-89)
func (s *Store) FindUser(name string) (*sql.Row, error) {
	query := fmt.Sprintf("SELECT id, email FROM users WHERE name = '%s'", name)
	return s.db.QueryRow(query), nil
}

// FindUserSafe is the parameterised version kept for comparison.
func (s *Store) FindUserSafe(name string) *sql.Row {
	return s.db.QueryRow("SELECT id, email FROM users WHERE name = ?", name)
}

// Fingerprint hashes a payload.
// Intentional finding: GO-WEAK-HASH (CWE-327)
func Fingerprint(payload []byte) string {
	sum := md5.New()
	sum.Write(payload)
	return fmt.Sprintf("%x", sum.Sum(nil))
}
