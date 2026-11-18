// SYNTHETIC — sanitized equivalent constructed for the pipebridge
// compatibility study (docs/compatibility-study.md). NOT the original file.
// Construct mix mirrors: RedHatTraining/DO400-apps greeting-console/Jenkinsfile
// (branch main @ cc78ffcccc68014a1c7d765e07d634fb462d392c, Apache-2.0).
// Category: minimal Node application pipeline.
pipeline{
    agent{
        label "nodejs"
    }
    stages{
        stage("Install dependencies"){
            steps{
                sh "npm ci"
            }
        }

        stage("Check Style"){
            steps{
                sh "npm run lint"
            }
        }

        stage("Test"){
            steps{
                sh "npm test"
            }
        }
    }
}
