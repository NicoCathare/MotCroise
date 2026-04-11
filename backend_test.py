#!/usr/bin/env python3
"""
Comprehensive backend API testing for French Crossword Generator
Tests all endpoints: init, propose, reject, place, upload, count
"""

import requests
import sys
import json
import tempfile
import os
from datetime import datetime

class CrosswordAPITester:
    def __init__(self, base_url="https://mot-croise-gen.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.session_id = None
        self.grid_state = None

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED {details}")
        else:
            print(f"❌ {name} - FAILED {details}")
        return success

    def run_api_test(self, name, method, endpoint, expected_status, data=None, files=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'} if not files else {}
        
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        if data:
            print(f"   Data: {json.dumps(data, indent=2)}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=data)
            elif method == 'POST':
                if files:
                    response = requests.post(url, files=files)
                else:
                    response = requests.post(url, json=data, headers=headers)
            
            print(f"   Status: {response.status_code}")
            
            success = response.status_code == expected_status
            
            if success:
                try:
                    response_data = response.json()
                    print(f"   Response: {json.dumps(response_data, indent=2)}")
                    return True, response_data
                except:
                    return True, {}
            else:
                try:
                    error_data = response.json()
                    print(f"   Error: {json.dumps(error_data, indent=2)}")
                except:
                    print(f"   Error: {response.text}")
                return False, {}

        except Exception as e:
            print(f"   Exception: {str(e)}")
            return False, {}

    def test_root_endpoint(self):
        """Test root API endpoint"""
        success, response = self.run_api_test(
            "Root API Endpoint",
            "GET", 
            "",
            200
        )
        return self.log_test("Root API", success, f"- {response.get('message', '')}")

    def test_word_count_default(self):
        """Test word count with default dictionary"""
        success, response = self.run_api_test(
            "Word Count (Default)",
            "GET",
            "words/count",
            200
        )
        if success:
            count = response.get('count', 0)
            is_custom = response.get('is_custom', False)
            details = f"- {count} words, custom: {is_custom}"
        else:
            details = ""
        return self.log_test("Word Count Default", success, details)

    def test_crossword_init_valid(self):
        """Test crossword initialization with valid data"""
        test_data = {
            "rows": 10,
            "cols": 10,
            "first_horizontal_word": "MAISON",
            "first_vertical_word": "ARBRE"
        }
        
        success, response = self.run_api_test(
            "Crossword Init (Valid)",
            "POST",
            "crossword/init",
            200,
            test_data
        )
        
        if success:
            self.grid_state = {
                "grid": response.get("grid", []),
                "rows": response.get("rows", 0),
                "cols": response.get("cols", 0),
                "words_placed": response.get("words_placed", [])
            }
            details = f"- Grid: {len(response.get('grid', []))}x{len(response.get('grid', [[]])[0] if response.get('grid') else [])}, Words: {len(response.get('words_placed', []))}"
        else:
            details = ""
            
        return self.log_test("Crossword Init Valid", success, details)

    def test_crossword_init_invalid(self):
        """Test crossword initialization with invalid data"""
        test_cases = [
            {
                "name": "No intersection",
                "data": {
                    "rows": 10,
                    "cols": 10,
                    "first_horizontal_word": "MAISON",
                    "first_vertical_word": "XYZT"
                },
                "expected": 400
            },
            {
                "name": "Word too long",
                "data": {
                    "rows": 5,
                    "cols": 5,
                    "first_horizontal_word": "MAISONTRESLONGUE",
                    "first_vertical_word": "ARBRE"
                },
                "expected": 400
            },
            {
                "name": "Short words",
                "data": {
                    "rows": 10,
                    "cols": 10,
                    "first_horizontal_word": "A",
                    "first_vertical_word": "B"
                },
                "expected": 400
            }
        ]
        
        all_passed = True
        for case in test_cases:
            success, _ = self.run_api_test(
                f"Crossword Init Invalid ({case['name']})",
                "POST",
                "crossword/init",
                case["expected"],
                case["data"]
            )
            if not success:
                all_passed = False
                
        return self.log_test("Crossword Init Invalid Cases", all_passed)

    def test_word_proposal(self):
        """Test word proposal functionality"""
        if not self.grid_state:
            return self.log_test("Word Proposal", False, "- No grid state available")
        
        # Test horizontal proposal
        success_h, response_h = self.run_api_test(
            "Word Proposal (Horizontal)",
            "POST",
            "crossword/propose",
            200,
            {
                "grid_state": self.grid_state,
                "direction": "horizontal"
            }
        )
        
        # Test vertical proposal
        success_v, response_v = self.run_api_test(
            "Word Proposal (Vertical)",
            "POST",
            "crossword/propose",
            200,
            {
                "grid_state": self.grid_state,
                "direction": "vertical"
            }
        )
        
        success = success_h and success_v
        details = ""
        if success_h and response_h.get("proposal"):
            details += f"H: {response_h['proposal'].get('original_word', 'N/A')} "
        if success_v and response_v.get("proposal"):
            details += f"V: {response_v['proposal'].get('original_word', 'N/A')}"
            
        return self.log_test("Word Proposal", success, f"- {details}")

    def test_word_reject(self):
        """Test word rejection functionality"""
        if not self.grid_state:
            return self.log_test("Word Reject", False, "- No grid state available")
        
        success, response = self.run_api_test(
            "Word Reject",
            "POST",
            "crossword/reject",
            200,
            {
                "grid_state": self.grid_state,
                "direction": "horizontal",
                "rejected_words": ["MAISON", "ARBRE"]
            }
        )
        
        details = ""
        if success and response.get("proposal"):
            details = f"- New proposal: {response['proposal'].get('original_word', 'N/A')}"
        elif success:
            details = f"- {response.get('message', 'No more words')}"
            
        return self.log_test("Word Reject", success, details)

    def test_word_placement(self):
        """Test word placement functionality"""
        if not self.grid_state:
            return self.log_test("Word Placement", False, "- No grid state available")
        
        # First get a proposal
        success_prop, response_prop = self.run_api_test(
            "Get Proposal for Placement",
            "POST",
            "crossword/propose",
            200,
            {
                "grid_state": self.grid_state,
                "direction": "horizontal"
            }
        )
        
        if not success_prop or not response_prop.get("proposal"):
            return self.log_test("Word Placement", False, "- No proposal available")
        
        proposal = response_prop["proposal"]
        
        # Try to place the word
        success, response = self.run_api_test(
            "Word Placement",
            "POST",
            "crossword/place",
            200,
            {
                "grid_state": self.grid_state,
                "word": proposal["word"],
                "direction": proposal["direction"],
                "row": proposal["row"],
                "col": proposal["col"]
            }
        )
        
        if success:
            # Update grid state for future tests
            self.grid_state = {
                "grid": response.get("grid", []),
                "rows": self.grid_state["rows"],
                "cols": self.grid_state["cols"],
                "words_placed": response.get("words_placed", [])
            }
            details = f"- Placed: {proposal.get('original_word', 'N/A')}, Total words: {len(response.get('words_placed', []))}"
        else:
            details = ""
            
        return self.log_test("Word Placement", success, details)

    def test_file_upload(self):
        """Test custom word list upload"""
        # Create a temporary file with French words
        test_words = [
            "BONJOUR",
            "MERCI", 
            "SALUT",
            "CHAT",
            "CHIEN",
            "MAISON",
            "ARBRE",
            "FLEUR",
            "SOLEIL",
            "LUNE",
            "ETOILE",
            "MONTAGNE",
            "RIVIERE",
            "OCEAN"
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            for word in test_words:
                f.write(word + '\n')
            temp_file_path = f.name
        
        try:
            # Test file upload
            with open(temp_file_path, 'rb') as f:
                files = {'file': ('test_words.txt', f, 'text/plain')}
                success, response = self.run_api_test(
                    "File Upload",
                    "POST",
                    "words/upload",
                    200,
                    files=files
                )
            
            if success:
                self.session_id = response.get("session_id")
                word_count = response.get("word_count", 0)
                details = f"- Session: {self.session_id[:8]}..., Words: {word_count}"
            else:
                details = ""
                
            return self.log_test("File Upload", success, details)
            
        finally:
            # Clean up temp file
            os.unlink(temp_file_path)

    def test_word_count_custom(self):
        """Test word count with custom dictionary"""
        if not self.session_id:
            return self.log_test("Word Count Custom", False, "- No session ID available")
        
        success, response = self.run_api_test(
            "Word Count (Custom)",
            "GET",
            "words/count",
            200,
            {"session_id": self.session_id}
        )
        
        if success:
            count = response.get('count', 0)
            is_custom = response.get('is_custom', False)
            details = f"- {count} words, custom: {is_custom}"
        else:
            details = ""
            
        return self.log_test("Word Count Custom", success, details)

    def test_invalid_endpoints(self):
        """Test invalid endpoints and methods"""
        test_cases = [
            ("GET", "crossword/nonexistent", 404, None),
            ("POST", "crossword/init", 422, {}),  # Empty data
            ("GET", "crossword/propose", 405, None),  # Wrong method
        ]
        
        all_passed = True
        for method, endpoint, expected_status, data in test_cases:
            success, _ = self.run_api_test(
                f"Invalid {method} {endpoint}",
                method,
                endpoint,
                expected_status,
                data if data is not None else None
            )
            if not success:
                all_passed = False
                
        return self.log_test("Invalid Endpoints", all_passed)

    def run_all_tests(self):
        """Run all backend tests"""
        print("🚀 Starting Crossword Generator Backend API Tests")
        print("=" * 60)
        
        # Basic connectivity
        self.test_root_endpoint()
        self.test_word_count_default()
        
        # Core crossword functionality
        self.test_crossword_init_valid()
        self.test_crossword_init_invalid()
        self.test_word_proposal()
        self.test_word_reject()
        self.test_word_placement()
        
        # File upload functionality
        self.test_file_upload()
        self.test_word_count_custom()
        
        # Error handling
        self.test_invalid_endpoints()
        
        # Summary
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return 1

def main():
    """Main test runner"""
    tester = CrosswordAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())