-- xjustiz.sql
-- Creates the courts lookup table used by COMPANY_ID_PKG for DE validation.
-- Court data is loaded separately by the test harness (XJustiz.json).

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE courts';
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/
CREATE TABLE courts (
    court_key  VARCHAR2(200) NOT NULL,
    court_code VARCHAR2(10)  NOT NULL,
    court_name VARCHAR2(200) NOT NULL,
    CONSTRAINT pk_courts PRIMARY KEY (court_key)
)
/
