// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: tutao/tutanota ci/Release.Jenkinsfile
// (branch master @ 324b7b87649343ad4859b307f7e640249d6fa745, GPL-3.0).
// Category: Node application, staged release orchestration with approval.
// would have preferred to do all client builds completely in parallel,
// but that would require nested parallel blocks which are not supported.
def releaseNotes

pipeline {
	environment {
		PATH = "${env.NODE_PATH}:${env.PATH}"
		VERSION = sh(returnStdout: true, script: "node -p -e \"require('./package.json').version\"")
	}

	parameters {
		choice(
			name: 'target',
			choices: ['staging', 'publishToProd'],
			defaultValue: 'staging',
		)
	}

	agent {
		label 'main'
	}

	stages {
		stage('Prepare') {
			steps {
				sh "npm ci"
				sh "npm run check"
			}
		}

		stage('Desktop build') {
			agent { label 'main' }
			steps {
				sh "npm run build-packages"
			}
		}

		stage('Release approval') {
			steps {
				script {
					timeout(time: 3, unit: 'DAYS') {
						input message: 'Review the draft release notes and approve publication.'
					}
					releaseNotes = readFile('RELEASE_NOTES.md')
				}
			}
		}

		stage('Publish') {
			when { expression { params.target.equals('publishToProd') } }
			steps {
				sh "npm run publish"
			}
		}
	}

	post {
		failure {
			mail to: 'release@example.org', subject: "release failed (${env.BRANCH_NAME})"
		}
	}
}

def pregenerateReleaseNotes(platform) {
	echo "pregenerate ${platform}"
}

def shouldBuild() {
	return true
}
